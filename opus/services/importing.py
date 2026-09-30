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
from django.db.models import Max
from docx import Document
from pypdf import PdfReader

from opus.models import Edition, SourceFile, TextUnit


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 5_000_000
MAX_PARAGRAPHS = 50_000
MAX_EPUB_UNCOMPRESSED_SIZE = 20 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2_000
MAX_PDF_PAGES = 5_000
MAX_PREVIEW_CHAPTERS = 1_000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".docx", ".epub", ".pdf"}
# How running text becomes reading units: one per sentence (prose) or one per line (verse, drama).
SEGMENT_SENTENCES = "sentences"
SEGMENT_LINES = "lines"
SEGMENTATIONS = (SEGMENT_SENTENCES, SEGMENT_LINES)
# How many pages a PDF running header/footer must repeat on before it is treated as furniture.
MIN_RUNNING_HEADER_PAGES = 3


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
    segmentation: str = SEGMENT_SENTENCES
    # Leading chapters (foreword, colophon, TOC...) ahead of the first numbered chapter.
    front_matter_count: int = 0

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


def import_document(edition, uploaded_file, *, extracted=None, label=""):
    """Extract an uploaded document in memory and persist its text units.

    A file without chapter headings becomes a single chapter named ``label`` (see
    ``titled_chapters``), so a chapter can later be appended after it.
    """

    extracted = extracted or extract_document(uploaded_file)
    with transaction.atomic():
        if edition.text_units.exists():
            raise DocumentImportError(
                "This edition already has imported text. Create a new edition to import another document."
            )
        source_file = _create_source_file(edition, extracted)
        _create_chapters(edition, titled_chapters(extracted, label))
    return source_file, extracted.paragraph_count


def append_document(edition, *, extracted, label=""):
    """Add an uploaded document's chapters after the text an edition already has.

    A file without chapter headings becomes a single chapter named ``label`` (see
    ``titled_chapters``). Its paragraphs follow the edition's last one, so the parallel grid
    simply grows at the end of that edition's column.
    """

    chapters = titled_chapters(extracted, label)
    with transaction.atomic():
        # Serialise concurrent appends to one edition, or both would take the same positions.
        Edition.objects.select_for_update().filter(pk=edition.pk).first()
        units = TextUnit.objects.filter(version=edition)
        last_top_level = units.filter(parent__isnull=True).aggregate(last=Max("position"))["last"] or 0
        last_paragraph = units.filter(kind=TextUnit.Kind.PARAGRAPH).aggregate(last=Max("position"))["last"] or 0
        source_file = _create_source_file(edition, extracted)
        _create_chapters(edition, chapters, chapter_start=last_top_level, paragraph_start=last_paragraph)
    return source_file, extracted.paragraph_count


def titled_chapters(extracted, label=""):
    """The chapters an import creates: the file's own, or - when it has no chapter headings -
    one chapter named ``label`` (or, without one, after the file) holding all of its text."""

    if any(chapter.label for chapter in extracted.chapters):
        return extracted.chapters
    return [
        ExtractedChapter(
            label=label.strip() or Path(extracted.filename).stem,
            paragraphs=[paragraph for chapter in extracted.chapters for paragraph in chapter.paragraphs],
        )
    ]


def _create_source_file(edition, extracted):
    return SourceFile.objects.create(
        version=edition,
        storage_key=f"memory:{edition.pk}:{extracted.content_hash[:16]}:{uuid4().hex[:12]}",
        original_filename=extracted.filename,
        content_hash=extracted.content_hash,
        file_type=extracted.file_type,
        import_status=SourceFile.ImportStatus.COMPLETED,
    )


def _create_chapters(edition, chapters, *, chapter_start=0, paragraph_start=0):
    """Persist chapters and their paragraphs, numbered on from the given positions."""

    chapter_units = TextUnit.objects.bulk_create(
        [
            TextUnit(
                version=edition,
                kind=TextUnit.Kind.CHAPTER,
                position=chapter_start + index,
                content="",
                label=chapter.label or "Inledning",
            )
            for index, chapter in enumerate(chapters, start=1)
        ]
    )
    paragraphs = []
    paragraph_position = paragraph_start
    for chapter, chapter_unit in zip(chapters, chapter_units):
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


def document_preview(edition, extracted, label=""):
    """Describe the chapters an import would create without persisting the file or text.

    ``edition`` may be ``None`` when previewing a file before its edition exists.
    """

    has_headings = any(chapter.label for chapter in extracted.chapters)
    chapters = titled_chapters(extracted, label)
    displayed_chapters = chapters[:MAX_PREVIEW_CHAPTERS]
    return {
        "edition": (
            {"id": edition.id, "title": edition.title, "language": edition.language} if edition is not None else None
        ),
        "segmentation": extracted.segmentation,
        "paragraph_count": extracted.paragraph_count,
        "chapter_count": len(chapters),
        # False when the file had no chapter headings and becomes one chapter named by ``label``.
        "has_headings": has_headings,
        "front_matter_count": extracted.front_matter_count,
        "preview_truncated": len(displayed_chapters) != len(chapters),
        "chapters": [
            {
                "position": position,
                "label": chapter.label or "Inledning",
                "paragraph_count": len(chapter.paragraphs),
                "preview": chapter.paragraphs[0][:500] if chapter.paragraphs else "",
                "front_matter": position <= extracted.front_matter_count,
            }
            for position, chapter in enumerate(displayed_chapters, start=1)
        ],
    }


def extract_document(uploaded_file, *, segmentation=SEGMENT_SENTENCES, keep_front_matter=True):
    """Read a supported upload without ever writing its bytes to disk.

    ``segmentation`` picks the reading unit (see ``SEGMENTATIONS``). Text ahead of the first
    numbered chapter is kept unless ``keep_front_matter`` is false.
    """

    if segmentation not in SEGMENTATIONS:
        raise DocumentImportError("Unsupported segmentation.")

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
    chapters = _split_chapters(text, segmentation=segmentation)
    front_matter_count = _front_matter_count(chapters)
    if not keep_front_matter:
        chapters = chapters[front_matter_count:]
        front_matter_count = 0
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
        segmentation=segmentation,
        front_matter_count=front_matter_count,
    )


def _extract_text(payload, extension):
    if extension in {".txt", ".md"}:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentImportError("Text documents must use UTF-8 encoding.") from exc
        # Markdown may start its chapters at "##"; promote the highest level used to "#".
        return _normalise_heading_levels(text) if extension == ".md" else text
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
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise DocumentImportError("Password-protected PDFs are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise DocumentImportError("The PDF contains too many pages.")
            page_texts = _strip_running_headers(
                [_strip_pdf_page_footer(page.extract_text() or "") for page in reader.pages]
            )
            outline_text = _pdf_outline_text(reader, page_texts)
            # A single newline between pages: a page break is layout, not the end of a paragraph,
            # and a sentence (or a hyphenated word) running over it must stay whole.
            return outline_text if outline_text is not None else "\n".join(page_texts)
        except DocumentImportError:
            raise
        except Exception as exc:
            raise DocumentImportError("The PDF document could not be read.") from exc
    raise DocumentImportError("Unsupported file type.")


_PDF_PAGE_FOOTER = re.compile(r"\n\d{1,4}\s*$")


def _strip_pdf_page_footer(page_text):
    """Drop the running header/page-number line pypdf leaves at the end of a page's text -
    it's typesetting furniture, not content, and otherwise ends up glued onto a sentence."""

    stripped = _PDF_PAGE_FOOTER.sub("", page_text)
    return stripped if stripped.strip() else page_text


def _running_header_key(line):
    """A page's first/last line with its page number removed, for spotting repeats."""

    return " ".join(re.sub(r"\d+", " ", line).split()).casefold()


def _strip_running_headers(page_texts):
    """Drop a running header or footer (the book or chapter title repeated at the top or
    bottom of every page) - otherwise it lands mid-sentence wherever a page breaks, and an
    all-caps one would even be taken for a new chapter on every page. A numbered chapter
    heading ("Kapitel 3") is never treated as one, even when chapters start on new pages."""

    def edge_lines(text):
        lines = [line for line in text.split("\n") if line.strip()]
        return (lines[0], lines[-1]) if lines else (None, None)

    edges = [edge_lines(text) for text in page_texts]
    counts = {}
    for first, last in edges:
        for line in {first, last} - {None}:
            key = _running_header_key(line)
            if key and not _numbered_heading(" ".join(line.split())):
                counts[key] = counts.get(key, 0) + 1
    repeated = {
        key
        for key, count in counts.items()
        if count >= MIN_RUNNING_HEADER_PAGES and count * 5 >= len(page_texts)
    }
    if not repeated:
        return page_texts

    stripped_pages = []
    for text, (first, last) in zip(page_texts, edges):
        lines = text.split("\n")
        for edge in (first, last):
            if edge is not None and _running_header_key(edge) in repeated and edge in lines:
                index = lines.index(edge) if edge == first else len(lines) - 1 - lines[::-1].index(edge)
                del lines[index]
        stripped_pages.append("\n".join(lines))
    return stripped_pages


def _pdf_outline_text(reader, page_texts):
    """Use the PDF's own bookmarks as chapter boundaries when it has them - a real table of
    contents beats guessing chapter breaks from how the running text happens to be laid out."""

    entries = []

    def collect(items):
        for item in items:
            if isinstance(item, list):
                collect(item)
                continue
            try:
                page_number = reader.get_destination_page_number(item)
            except Exception:
                continue
            title = _short_title(item.title) or " ".join((item.title or "").split())
            if title:
                entries.append((page_number, title))

    try:
        collect(reader.outline)
    except Exception:
        return None
    entries = [entry for entry in entries if 0 <= entry[0] < len(page_texts)]
    entries.sort(key=lambda entry: entry[0])
    if len(entries) < 2:
        return None

    # A bookmark only points to a page, not a text offset. A chapter that ends partway down a
    # page (common for short chapters) leaves the next chapter's heading sitting further down
    # that very page - slicing by whole pages would then glue the next chapter's opening onto
    # the tail of the previous one. Pin each entry to the exact line its heading starts on
    # whenever the title has a "Kapitel/Chapter N" number to search for; page boundaries are
    # only a fallback for entries (section dividers, the foreword) that lack one.
    full_text = "\n".join(page_texts)
    page_offsets = []
    offset = 0
    for page_text in page_texts:
        page_offsets.append(offset)
        offset += len(page_text) + 1

    def locate(page_number, title):
        anchor = re.match(r"(?i)^(kapitel|chapter|revelation)\s+([\wåÅäÄöÖ]+)", title.strip())
        page_start = page_offsets[page_number]
        if not anchor:
            return page_start, None
        window_start = page_offsets[max(page_number - 1, 0)]
        window_end = page_offsets[min(page_number + 1, len(page_offsets) - 1)] + 400
        pattern = re.compile(
            r"(?m)^" + re.escape(anchor.group(1)) + r"\s+" + re.escape(anchor.group(2)) + r"\b[^\n]*\n?",
            re.IGNORECASE,
        )
        match = pattern.search(full_text, window_start, window_end)
        return (match.start(), match) if match else (page_start, None)

    located = [locate(page_number, title) for page_number, title in entries]
    positions = [position for position, _ in located]
    chapters = []
    for index, (position, match) in enumerate(located):
        title = entries[index][1]
        end = positions[index + 1] if index + 1 < len(positions) else len(full_text)
        if end <= position:
            continue
        # The heading line we just located is the book's own "Kapitel N ..." text; skip it in
        # the body so it isn't duplicated alongside the "# title" we add for the chapter.
        body_start = match.end() if match else position
        chapters.append(f"# {title}\n\n{full_text[body_start:end]}")
    return "\n\n".join(chapters)


# Sentence-final punctuation, any closing quotes/brackets after it, then whitespace.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'»«”’)\]]*\s+")
# Any sentence-final punctuation at all; prose always has some.
_SENTENCE_MARK = re.compile(r"[.!?…]")
# Characters that may open a sentence ahead of its first letter (quotes, dialogue dashes).
_SENTENCE_OPENERS = "\"'»«“”‘’([–—- "
# Undotted abbreviations (casefolded, without the final period) that never end a sentence.
# Dotted ones ("t.ex.", "d.v.s.", "e.g.") are recognised by their shape instead.
_ABBREVIATIONS = frozenset(
    {
        "ca", "jfr", "kap", "nr", "resp", "sid", "uppl", "övers", "utg", "red", "fig", "vol",
        "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "cf", "ch", "hr", "fr",
    }
)
_DOTTED_ABBREVIATION = re.compile(r"(?:\w{1,4}\.)+\w{1,4}")


def _is_sentence_boundary(text, start, match):
    """A sentence ends at ``match`` only when the next one starts with a capital letter and the
    period doesn't belong to an abbreviation or an initial ("t.ex. att", "s. 12", "C. S. Lewis")."""

    following = text[match.end():].lstrip(_SENTENCE_OPENERS)
    if not following or not following[0].isupper():
        return False
    if not match.group().startswith("."):
        return True
    words = text[start:match.start()].split()
    word = words[-1].lstrip(_SENTENCE_OPENERS) if words else ""
    if word.casefold() in _ABBREVIATIONS or _DOTTED_ABBREVIATION.fullmatch(word):
        return False
    return not (len(word) == 1 and word.isupper())


def _split_sentences(text):
    """Comparing editions line-by-line needs a unit smaller than a whole page: one sentence,
    not the block of running text a page happens to contain."""

    sentences = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        if _is_sentence_boundary(text, start, match):
            sentence = text[start:match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


_LINE_WRAP_HYPHEN = re.compile(r"([a-zA-ZåäöÅÄÖ])-\n([a-zA-ZåäöÅÄÖ])")


def _split_chapters(text, *, segmentation=SEGMENT_SENTENCES):
    lines_mode = segmentation == SEGMENT_LINES
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not lines_mode:
        # Undo the soft hyphen a justified layout leaves at a line-wrap (e.g. "träng-\ner"):
        # it's one word split by the page width, not a real hyphenated compound. In verse a
        # line break is the text itself, so it is left alone there.
        normalized = _LINE_WRAP_HYPHEN.sub(r"\1\2", normalized)
    # A document that already marks its own headings (epub, html, docx) gets its structure
    # entirely from those explicit "#" markers. The loose heuristics below (a numbered
    # "Kapitel 3" line, an ALL-CAPS line) exist only to find chapters in plain text/PDF
    # uploads that have no markup at all - applying them on top of an already-structured
    # document just fragments real chapters on incidental all-caps subtitles.
    allow_heuristics = not re.search(r"(?m)^#\s", normalized)
    chapters = []
    label = ""
    paragraphs = []
    buffer = []

    def flush_paragraph():
        if buffer:
            # Verse and drama keep every line as its own unit; prose is re-cut into sentences.
            # A multi-line block without a single sentence mark is verse even in prose mode
            # (e.g. an unpunctuated medieval text): joined, it would become one giant "sentence".
            keep_lines = lines_mode or (len(buffer) > 1 and not _SENTENCE_MARK.search(" ".join(buffer)))
            paragraphs.extend(buffer if keep_lines else _split_sentences(" ".join(buffer)))
            buffer.clear()

    def finish_chapter():
        flush_paragraph()
        if paragraphs:
            chapters.append(ExtractedChapter(label=label, paragraphs=paragraphs.copy()))

    for raw_line in normalized.split("\n"):
        line = " ".join(raw_line.split())
        if not line:
            flush_paragraph()
            continue
        # A heading is recognised per physical line, not per blank-line-separated paragraph:
        # PDF text extraction routinely runs a chapter heading straight into the surrounding
        # text with no blank line around it, so waiting for one would silently merge chapters.
        # An all-caps line is a speaker's name in drama, not a chapter, so it only counts as a
        # heading in prose.
        heading = _chapter_heading(line, allow_heuristics=allow_heuristics, allow_caps=not lines_mode)
        if heading is not None and not _repeats_pending_label(heading, label, paragraphs or buffer):
            finish_chapter()
            label = heading
            paragraphs = []
        else:
            buffer.append(line)
    finish_chapter()
    return chapters


_FIRST_CHAPTER = re.compile(r"(?i:chapter|kapitel)\s*(?:1|I|(?i:one|ett|första))\b|(?i:första\s+kapitlet)\b")


def _front_matter_count(chapters):
    """How many leading chapters (cover, colophon, TOC, foreword) come before the first
    numbered chapter. Editions are compared chapter-by-chapter, so an importer may want to
    skip them - but that is the reader's choice, never a silent default."""

    return next(
        (index for index, chapter in enumerate(chapters) if _FIRST_CHAPTER.match(chapter.label.strip())),
        0,
    )


def _repeats_pending_label(candidate, label, paragraphs):
    """Don't let a loosely-matched heading (e.g. an all-caps subtitle) overwrite a chapter
    heading that was just set and has no content yet, when it just repeats that label."""

    return bool(label) and not paragraphs and candidate.strip().casefold() == label.strip().casefold()


# Longest line a heuristic (unmarked) heading may be; running text is longer.
MAX_HEURISTIC_HEADING = 100
_STRUCTURE_WORDS = r"chapter|kapitel|book|bok|part|del|capitulum|cap\.?|liber|pars"
_NUMBER_WORDS = r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
_ORDINAL_WORDS = r"första|andra|tredje|fjärde|femte|sjätte|sjunde|åttonde|nionde|tionde"
# "Kapitel 3", "Del IV: Hemkomsten", "Chapter Two" - a structure word needs its number, or
# ordinary sentences ("del av staden ...", "Part of the ...") start new chapters. Roman
# numerals must be upper case for the same reason ("del i staden").
_NUMBERED_HEADING = re.compile(
    rf"(?i:{_STRUCTURE_WORDS})\s+(?:\d{{1,4}}|[IVXLCDM]{{1,8}}|(?i:{_NUMBER_WORDS}))\b(?:[.:)]?(?:\s.*)?)"
    rf"|(?i:{_ORDINAL_WORDS})\s+(?i:kapitlet|delen|boken)\b.*"
)
_STANDALONE_HEADING = re.compile(r"(?i)(?:prologus|praefatio|prefatio)\b[^.!?]*")


def _numbered_heading(content):
    return len(content) <= MAX_HEURISTIC_HEADING and bool(_NUMBERED_HEADING.fullmatch(content))


def _chapter_heading(content, *, allow_heuristics=True, allow_caps=True):
    """Recognise explicit structural headings across modern and historical texts."""

    markdown = re.fullmatch(r"#\s+(.{1,255}?)\s*#*", content)
    if markdown:
        return markdown.group(1).strip()
    if not allow_heuristics or len(content) > MAX_HEURISTIC_HEADING:
        return None
    if _numbered_heading(content) or _STANDALONE_HEADING.fullmatch(content):
        return content
    if allow_caps and re.fullmatch(r"[A-ZÅÄÖ][A-ZÅÄÖ\s.\-–—]{2,}", content):
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
            items = {
                node.attrib["id"]: node.attrib
                for node in package.iter()
                if _local_name(node.tag) == "item" and "id" in node.attrib and "href" in node.attrib
            }
            manifest = {item_id: attrib["href"] for item_id, attrib in items.items()}
            spine = [
                node.attrib.get("idref")
                for node in package.iter()
                if _local_name(node.tag) == "itemref"
            ]
            package_directory = dirname(rootfile)
            nav_titles = _epub_nav_titles(archive, package, items, package_directory)
            chapters = []
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
                label = nav_titles.get(chapter_path) or _epub_chapter_label(chapter, chapter_text) or f"Chapter {index}"
                chapters.append(f"# {label}\n\n{chapter_text}")
            return "\n\n".join(chapters)
    except DocumentImportError:
        raise
    except (BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise DocumentImportError("The EPUB document could not be read.") from exc


def _epub_nav_titles(archive, package, items, package_directory):
    """Read the EPUB's own table of contents so chapter labels match the author's, not a guess per file."""

    nav_href = next(
        (
            attrib["href"]
            for attrib in items.values()
            if "nav" in attrib.get("properties", "").split()
        ),
        None,
    )
    if nav_href:
        nav_path = normpath(f"{package_directory}/{nav_href}" if package_directory else nav_href)
        try:
            nav_document = _parse_epub_xml(archive.read(nav_path))
        except (DocumentImportError, KeyError):
            nav_document = None
        if nav_document is not None:
            titles = _titles_from_nav_xhtml(nav_document, dirname(nav_path))
            if titles:
                return titles

    spine_node = next((node for node in package.iter() if _local_name(node.tag) == "spine"), None)
    ncx_id = spine_node.attrib.get("toc") if spine_node is not None else None
    ncx_href = items.get(ncx_id, {}).get("href") if ncx_id else next(
        (attrib["href"] for attrib in items.values() if attrib.get("media-type") == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_href:
        ncx_path = normpath(f"{package_directory}/{ncx_href}" if package_directory else ncx_href)
        try:
            ncx_document = _parse_epub_xml(archive.read(ncx_path))
        except (DocumentImportError, KeyError):
            return {}
        return _titles_from_ncx(ncx_document, dirname(ncx_path))
    return {}


def _titles_from_ncx(ncx_document, nav_directory):
    titles = {}
    for nav_point in ncx_document.iter():
        if _local_name(nav_point.tag) != "navPoint":
            continue
        label_text = next(
            (
                "".join(text_node.text or "" for text_node in nav_label_node)
                for nav_label_node in nav_point
                if _local_name(nav_label_node.tag) == "navLabel"
                for text_node in [next((n for n in nav_label_node if _local_name(n.tag) == "text"), None)]
                if text_node is not None
            ),
            None,
        )
        content_node = next((n for n in nav_point if _local_name(n.tag) == "content"), None)
        if not label_text or content_node is None:
            continue
        src = content_node.attrib.get("src")
        if not src:
            continue
        path = normpath(f"{nav_directory}/{src.split('#', 1)[0]}" if nav_directory else src.split("#", 1)[0])
        title = _short_title(label_text) or " ".join(label_text.split())
        if title and path not in titles:
            titles[path] = title
    return titles


def _titles_from_nav_xhtml(nav_document, nav_directory):
    toc_nav = next(
        (
            node
            for node in nav_document.iter()
            if _local_name(node.tag) == "nav"
            and any(_local_name(key) == "type" and value == "toc" for key, value in node.attrib.items())
        ),
        None,
    )
    if toc_nav is None:
        return {}
    titles = {}
    for link in toc_nav.iter():
        if _local_name(link.tag) != "a":
            continue
        href = link.attrib.get("href")
        if not href:
            continue
        title = _short_title("".join(link.itertext())) or " ".join("".join(link.itertext()).split())
        path = normpath(f"{nav_directory}/{href.split('#', 1)[0]}" if nav_directory else href.split("#", 1)[0])
        if title and path not in titles:
            titles[path] = title
    return titles


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
