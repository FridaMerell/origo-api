"""Import a PDF's own footnote/commentary links as marginal Annotations.

Some scholarly PDFs mark a discussed passage with an invisible link
annotation whose rectangle covers the exact quoted text, pointing to a page
in the book's own commentary section. This turns those links into
`Annotation` rows anchored on the matching `TextUnit`, instead of leaving
them as dead navigation the reader can only use inside a PDF viewer.
"""

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from opus.models import Annotation, TextUnit
from opus.services.importing import (
    DocumentImportError,
    MAX_PDF_PAGES,
    _split_sentences,
    _strip_pdf_page_footer,
)

MAX_NOTE_BODY_CHARS = 600


@dataclass(frozen=True)
class PdfNoteImportResult:
    link_count: int
    matched_source_count: int
    matched_destination_count: int
    created_count: int


def import_pdf_footnotes(edition, uploaded_file):
    """Read an already-imported edition's own PDF again and attach its footnote
    links as Annotations on the matching sentences. Read-only against the PDF;
    the edition must already have its TextUnits imported."""

    payload = uploaded_file.read()
    if not payload:
        raise DocumentImportError("The uploaded document is empty.")
    try:
        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise DocumentImportError("Password-protected PDFs are not supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentImportError("The PDF contains too many pages.")
    except DocumentImportError:
        raise
    except (PdfReadError, Exception) as exc:
        raise DocumentImportError("The PDF document could not be read.") from exc

    units = list(
        TextUnit.objects.filter(version=edition, kind=TextUnit.Kind.PARAGRAPH).order_by("position", "id")
    )
    if not units:
        raise DocumentImportError("This edition has no imported paragraphs to anchor notes on.")

    corpus = _build_corpus_index(units)
    page_texts = [_strip_pdf_page_footer(page.extract_text() or "") for page in reader.pages]

    links = list(_iter_goto_links(reader))
    matched_source = 0
    matched_destination = 0
    created = 0
    existing_bodies = {
        (annotation.unit_id, annotation.body)
        for annotation in Annotation.objects.filter(unit__version=edition, kind="footnote")
    }

    for page_index, rect, dest in links:
        source_text = _text_in_rect(reader.pages[page_index], rect)
        if not source_text.strip():
            continue
        matched_source += 1
        unit = _match_unit(corpus, source_text)
        if unit is None:
            continue

        body = _destination_text(reader, page_texts, dest)
        if not body:
            continue
        matched_destination += 1

        key = (unit.id, body)
        if key in existing_bodies:
            continue
        existing_bodies.add(key)
        Annotation.objects.create(
            unit=unit,
            user=edition.work.owner,
            kind="footnote",
            target_kind=Annotation.TargetKind.UNIT,
            body=body,
        )
        created += 1

    return PdfNoteImportResult(
        link_count=len(links),
        matched_source_count=matched_source,
        matched_destination_count=matched_destination,
        created_count=created,
    )


def _iter_goto_links(reader):
    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots.get_object():
            obj = ref.get_object()
            action = obj.get("/A")
            if not action or action.get("/S") != "/GoTo":
                continue
            dest = action.get("/D")
            rect = obj.get("/Rect")
            if not dest or not rect:
                continue
            yield page_index, [float(value) for value in rect], dest


def _text_in_rect(page, rect, pad=2.0):
    x0, y0, x1, y1 = rect
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    spans = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        x = (cm[4] if cm else 0) + (tm[4] if tm else 0)
        y = (cm[5] if cm else 0) + (tm[5] if tm else 0)
        if x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad:
            spans.append(text)

    page.extract_text(visitor_text=visitor)
    return "".join(spans)


def _resolve_destination_page(reader, dest):
    if not isinstance(dest, list) or not dest:
        return None
    target_idnum = getattr(dest[0], "idnum", None)
    if target_idnum is None:
        return None
    for index, page in enumerate(reader.pages):
        ref = page.indirect_reference
        if ref is not None and ref.idnum == target_idnum:
            return index
    return None


def _destination_text(reader, page_texts, dest):
    """Pull the commentary text starting at a link's target page/position."""

    page_number = _resolve_destination_page(reader, dest)
    if page_number is None or not (0 <= page_number < len(page_texts)):
        return ""
    # A /XYZ destination array is [page, /XYZ, left, top, zoom] - the vertical anchor is top.
    top_y = dest[3] if isinstance(dest, list) and len(dest) > 3 and isinstance(dest[3], (int, float)) else None

    if top_y is None:
        window_text = page_texts[page_number]
    else:
        spans = []

        def visitor(text, cm, tm, font_dict, font_size):
            if not text or not text.strip():
                return
            y = (cm[5] if cm else 0) + (tm[5] if tm else 0)
            if y <= top_y + 2:
                spans.append((y, text))

        reader.pages[page_number].extract_text(visitor_text=visitor)
        spans.sort(key=lambda item: -item[0])
        window_text = "".join(text for _, text in spans)
        if not window_text.strip():
            window_text = page_texts[page_number]

    sentences = _split_sentences(" ".join(window_text.split()))
    if not sentences:
        return ""
    body = " ".join(sentences[:2])
    return body[:MAX_NOTE_BODY_CHARS].strip()


_NORMALISE = re.compile(r"\s+")


def _normalise(text):
    return _NORMALISE.sub(" ", text).strip().casefold()


def _build_corpus_index(units):
    """A normalised copy of each unit's opening text, for matching a link's quoted
    passage back to the sentence it starts in."""

    return [(unit, _normalise(unit.content)[:120]) for unit in units]


def _match_unit(corpus, source_text, anchor_chars=40):
    anchor = _normalise(source_text)[:anchor_chars]
    if not anchor:
        return None
    for unit, normalised in corpus:
        if normalised.startswith(anchor) or anchor.startswith(normalised) and normalised:
            return unit
    for unit, normalised in corpus:
        if anchor in normalised or (normalised and normalised[:anchor_chars] in anchor):
            return unit
    return None
