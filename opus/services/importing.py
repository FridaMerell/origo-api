"""In-memory document extraction, preview, and persistence as readable text units."""

from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from posixpath import dirname, normpath
import re
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from django.db import transaction
from docx import Document
from pypdf import PdfReader

from opus.models import SourceFile, TextUnit


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 5_000_000
MAX_PARAGRAPHS = 50_000
MAX_EPUB_UNCOMPRESSED_SIZE = 20 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2_000
MAX_PDF_PAGES = 5_000
MAX_PREVIEW_CHAPTERS = 1_000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".docx", ".epub", ".pdf"}


class DocumentImportError(ValueError):
    """A safe validation error for a submitted document."""


@dataclass(frozen=True)
class ExtractedChapter:
    """A chapter heading and the paragraphs assigned to it during import."""

    label: str
    paragraphs: list[str]


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    file_type: str
    content_hash: str
    chapters: list[ExtractedChapter]

    @property
    def paragraph_count(self):
        return sum(len(chapter.paragraphs) for chapter in self.chapters)


class _HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section"}
    IGNORED_TAGS = {"head", "script", "style", "svg", "title"}

    def __init__(self, *, mark_headings=True):
        super().__init__()
        self.parts = []
        self.ignored_depth = 0
        self.mark_headings = mark_headings

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            marker = "#" * int(tag[1]) if self.mark_headings else ""
            self.parts.append(f"\n\n{marker} " if marker else "\n")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        if self.ignored_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self):
        return "".join(self.parts)


class _EPUBTitleExtractor(HTMLParser):
    """Read semantic chapter titles without treating every HTML heading as a chapter."""

    TITLE_TOKENS = {"chapter", "chap", "title", "rubrik", "heading"}

    def __init__(self):
        super().__init__()
        self.open_titles = []
        self.titles = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = " ".join(value or "" for name, value in attrs if name in {"class", "id"})
        is_title = tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or any(
            token in attributes.casefold() for token in self.TITLE_TOKENS
        )
        if is_title:
            self.open_titles.append((tag, []))

    def handle_data(self, data):
        for _, parts in self.open_titles:
            parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.open_titles and self.open_titles[-1][0] == tag:
            _, parts = self.open_titles.pop()
            title = _short_title("".join(parts))
            if title:
                self.titles.append(title)


def import_document(edition, uploaded_file, *, extracted=None):
    """Extract an uploaded document in memory and persist its text units."""

    extracted = extracted or extract_document(uploaded_file)
    with transaction.atomic():
        if edition.text_units.exists():
            raise DocumentImportError(
                "This edition already has imported text. Create a new edition to import another document."
            )
        source_file = SourceFile.objects.create(
            version=edition,
            storage_key=f"memory:{edition.pk}:{extracted.content_hash[:16]}:{uuid4().hex[:12]}",
            original_filename=extracted.filename,
            content_hash=extracted.content_hash,
            file_type=extracted.file_type,
            import_status=SourceFile.ImportStatus.COMPLETED,
        )
        has_chapters = any(chapter.label for chapter in extracted.chapters)
        paragraph_position = 0
        if has_chapters:
            chapters = TextUnit.objects.bulk_create(
                [
                    TextUnit(
                        version=edition,
                        kind=TextUnit.Kind.CHAPTER,
                        position=index,
                        content="",
                        label=chapter.label or "Inledning",
                    )
                    for index, chapter in enumerate(extracted.chapters, start=1)
                ]
            )
            paragraphs = []
            for chapter, chapter_unit in zip(extracted.chapters, chapters):
                for paragraph in chapter.paragraphs:
                    paragraph_position += 1
                    paragraphs.append(
                        TextUnit(
                            version=edition,
                            parent=chapter_unit,
                            kind=TextUnit.Kind.PARAGRAPH,
                            position=paragraph_position,
                            content=paragraph,
                        )
                    )
            TextUnit.objects.bulk_create(paragraphs)
        else:
            TextUnit.objects.bulk_create(
                [
                    TextUnit(
                        version=edition,
                        kind=TextUnit.Kind.PARAGRAPH,
                        position=index,
                        content=paragraph,
                    )
                    for index, paragraph in enumerate(extracted.chapters[0].paragraphs, start=1)
                ]
            )
    return source_file, extracted.paragraph_count


def document_preview(edition, extracted):
    """Describe a proposed chapter index without persisting the uploaded file or text."""

    creates_chapters = any(chapter.label for chapter in extracted.chapters)
    displayed_chapters = extracted.chapters[:MAX_PREVIEW_CHAPTERS]
    return {
        "edition": {"id": edition.id, "title": edition.title, "language": edition.language},
        "paragraph_count": extracted.paragraph_count,
        "chapter_count": len(extracted.chapters) if creates_chapters else 0,
        "preview_truncated": len(displayed_chapters) != len(extracted.chapters),
        "chapters": [
            {
                "position": position,
                "label": chapter.label or ("Inledning" if creates_chapters else "Unindelad text"),
                "paragraph_count": len(chapter.paragraphs),
                "preview": chapter.paragraphs[0][:500] if chapter.paragraphs else "",
            }
            for position, chapter in enumerate(displayed_chapters, start=1)
        ],
    }


def extract_document(uploaded_file):
    """Read a supported upload without ever writing its bytes to disk."""

    filename = Path(uploaded_file.name or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DocumentImportError(f"Unsupported file type. Use one of: {allowed}.")
    if uploaded_file.size > MAX_FILE_SIZE:
        raise DocumentImportError("The document must be at most 10 MB.")

    payload = uploaded_file.read()
    if not payload:
        raise DocumentImportError("The uploaded document is empty.")
    if len(payload) > MAX_FILE_SIZE:
        raise DocumentImportError("The document must be at most 10 MB.")
    text = _extract_text(payload, extension)
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise DocumentImportError("The extracted text is too large to import.")
    chapters = _split_chapters(text)
    paragraph_count = sum(len(chapter.paragraphs) for chapter in chapters)
    if paragraph_count > MAX_PARAGRAPHS:
        raise DocumentImportError("The document contains too many paragraphs to import.")
    if not paragraph_count:
        raise DocumentImportError("No readable text was found in the document.")
    return ExtractedDocument(
        filename=filename,
        file_type=extension.removeprefix("."),
        content_hash=sha256(payload).hexdigest(),
        chapters=chapters,
    )


def _extract_text(payload, extension):
    if extension in {".txt", ".md"}:
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentImportError("Text documents must use UTF-8 encoding.") from exc
    if extension in {".html", ".htm"}:
        try:
            html = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentImportError("HTML documents must use UTF-8 encoding.") from exc
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return _normalise_heading_levels(parser.text())
    if extension == ".docx":
        _validate_zip_payload(payload, MAX_DOCX_UNCOMPRESSED_SIZE, "The DOCX document could not be read.")
        try:
            document = Document(BytesIO(payload))
        except Exception as exc:
            raise DocumentImportError("The DOCX document could not be read.") from exc
        blocks = []
        heading_levels = []
        for paragraph in document.paragraphs:
            content = paragraph.text.strip()
            if not content:
                continue
            style_name = (paragraph.style.name or "").casefold()
            match = re.search(r"(?:heading|rubrik)\s*(\d+)?", style_name)
            level = int(match.group(1) or 1) if match else None
            if level is not None:
                heading_levels.append(level)
            blocks.append((content, level))
        base_level = min(heading_levels, default=None)
        return "\n\n".join(
            f"{'#' * (level - base_level + 1)} {content}" if level is not None else content
            for content, level in blocks
        )
    if extension == ".epub":
        return _extract_epub_text(payload)
    if extension == ".pdf":
        try:
            reader = PdfReader(BytesIO(payload))
            if reader.is_encrypted:
                raise DocumentImportError("Password-protected PDFs are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise DocumentImportError("The PDF contains too many pages.")
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except DocumentImportError:
            raise
        except Exception as exc:
            raise DocumentImportError("The PDF document could not be read.") from exc
    raise DocumentImportError("Unsupported file type.")


def _split_chapters(text):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", normalized)
    chapters = []
    label = ""
    paragraphs = []

    def finish_chapter():
        if paragraphs:
            chapters.append(ExtractedChapter(label=label, paragraphs=paragraphs.copy()))

    for block in blocks:
        lines = [" ".join(line.split()) for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        first_line_heading = _chapter_heading(lines[0])
        if first_line_heading is not None:
            finish_chapter()
            label = first_line_heading
            paragraphs = []
            remainder = " ".join(lines[1:])
            if remainder:
                paragraphs.append(remainder)
            continue
        content = " ".join(lines)
        if not content:
            continue
        heading = _chapter_heading(content)
        if heading is not None:
            finish_chapter()
            label = heading
            paragraphs = []
        else:
            paragraphs.append(content)
    finish_chapter()
    return chapters


def _chapter_heading(content):
    """Recognise explicit structural headings across modern and historical texts."""

    markdown = re.fullmatch(r"#\s+(.{1,255}?)\s*#*", content)
    if markdown:
        return markdown.group(1).strip()
    if len(content) > 255:
        return None
    if re.fullmatch(
        r"(?i)(?:chapter|kapitel|book|bok|part|del|capitulum|cap\.?|liber|pars|prologus|praefatio|prefatio)\b.*",
        content,
    ):
        return content
    if re.fullmatch(r"[A-ZÅÄÖ][A-ZÅÄÖ\s.\-–—]{2,254}", content):
        return content
    return None


def _normalise_heading_levels(text):
    """Promote a document's highest heading level to a chapter heading."""

    levels = [
        len(match.group(1))
        for match in re.finditer(r"(?m)^(#{1,6})\s+", text)
    ]
    if not levels:
        return text
    base_level = min(levels)
    return re.sub(
        r"(?m)^(#{1,6})(\s+)",
        lambda match: "#" * (len(match.group(1)) - base_level + 1) + match.group(2),
        text,
    )


def _extract_epub_text(payload):
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            _validate_zip_entries(entries, MAX_EPUB_UNCOMPRESSED_SIZE, "The EPUB expands to too much text.")
            container_payload = archive.read("META-INF/container.xml")
            container = _parse_epub_xml(container_payload)
            rootfile = next(
                (node.attrib.get("full-path") for node in container.iter() if _local_name(node.tag) == "rootfile"),
                None,
            )
            if not rootfile:
                raise DocumentImportError("The EPUB has no package document.")
            package = _parse_epub_xml(archive.read(rootfile))
            manifest = {
                node.attrib["id"]: node.attrib["href"]
                for node in package.iter()
                if _local_name(node.tag) == "item" and "id" in node.attrib and "href" in node.attrib
            }
            spine = [
                node.attrib.get("idref")
                for node in package.iter()
                if _local_name(node.tag) == "itemref"
            ]
            chapters = []
            package_directory = dirname(rootfile)
            for index, item_id in enumerate(spine, start=1):
                href = manifest.get(item_id)
                if not href:
                    continue
                chapter_path = normpath(f"{package_directory}/{href}" if package_directory else href)
                try:
                    chapter = archive.read(chapter_path).decode("utf-8")
                except KeyError as exc:
                    raise DocumentImportError("The EPUB references a missing chapter.") from exc
                except UnicodeDecodeError as exc:
                    raise DocumentImportError("The EPUB contains a chapter that is not UTF-8 encoded.") from exc
                parser = _HTMLTextExtractor(mark_headings=False)
                parser.feed(chapter)
                chapter_text = parser.text()
                label = _epub_chapter_label(chapter, chapter_text) or f"Chapter {index}"
                chapters.append(f"## {label}\n\n{chapter_text}")
            return "\n\n".join(chapters)
    except DocumentImportError:
        raise
    except (BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise DocumentImportError("The EPUB document could not be read.") from exc


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _validate_zip_payload(payload, maximum_size, error_message):
    try:
        with ZipFile(BytesIO(payload)) as archive:
            _validate_zip_entries(archive.infolist(), maximum_size, error_message)
    except (BadZipFile, OSError) as exc:
        raise DocumentImportError(error_message) from exc


def _validate_zip_entries(entries, maximum_size, error_message):
    if len(entries) > MAX_ARCHIVE_ENTRIES or sum(entry.file_size for entry in entries) > maximum_size:
        raise DocumentImportError(error_message)


def _parse_epub_xml(payload):
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", payload, flags=re.IGNORECASE):
        raise DocumentImportError("The EPUB document could not be read.")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise DocumentImportError("The EPUB document could not be read.") from exc


def _epub_chapter_label(html, extracted_text):
    """Find an EPUB document's own chapter title before falling back to its spine order."""

    parser = _EPUBTitleExtractor()
    parser.feed(html)
    if parser.titles:
        return next(
            (title for title in parser.titles if not _is_generic_chapter_label(title)),
            parser.titles[0],
        )
    for line in extracted_text.splitlines():
        label = _short_title(line)
        if label and not label.startswith("## "):
            return label
    return ""


def _short_title(value):
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    text = " ".join(text.split())
    if not text or len(text) > 160 or re.search(r"[.!?]$", text):
        return ""
    return text


def _is_generic_chapter_label(label):
    return bool(
        re.fullmatch(
            r"(?i)(?:chapter|kapitel|capitulum|cap\.?|liber|book|bok|part|del)\s+(?:\d+|[ivxlcdm]+)",
            label.strip(),
        )
    )
