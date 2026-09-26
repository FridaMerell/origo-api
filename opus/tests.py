from types import SimpleNamespace

from django.test import SimpleTestCase

from opus.services.importing import (
    ExtractedChapter,
    ExtractedDocument,
    _epub_chapter_label,
    _split_chapters,
    document_preview,
)
from opus.views.alignment import AlignmentSetViewSet


class ChapterImportTests(SimpleTestCase):
    def test_title_on_line_after_heading_stays_in_the_same_chapter(self):
        chapters = _split_chapters("Kapitel 1\nFörsta stycket.\n\nKapitel 2\nAndra stycket.")

        self.assertEqual([(chapter.label, chapter.paragraphs) for chapter in chapters], [
            ("Kapitel 1", ["Första stycket."]),
            ("Kapitel 2", ["Andra stycket."]),
        ])

    def test_epub_prefers_the_specific_title_over_a_generic_number(self):
        label = _epub_chapter_label("<h1>Chapter 5</h1><h2>Prolog</h2>", "Chapter 5\nProlog")

        self.assertEqual(label, "Prolog")

    def test_preview_counts_the_same_chapters_that_import_creates(self):
        extracted = ExtractedDocument(
            filename="text.txt",
            file_type="txt",
            content_hash="hash",
            chapters=[
                ExtractedChapter(label="", paragraphs=["Inledning"]),
                ExtractedChapter(label="Kapitel 1", paragraphs=["Text"]),
            ],
        )

        preview = document_preview(SimpleNamespace(id=1, title="Test", language="sv"), extracted)

        self.assertEqual(preview["chapter_count"], 2)
        self.assertEqual(preview["chapters"][0]["label"], "Inledning")


class ChapterAlignmentTests(SimpleTestCase):
    def test_label_normalisation_preserves_words(self):
        self.assertEqual(
            AlignmentSetViewSet._normalise_label("Capitulum Prīmum!"),
            "capitulum primum",
        )
