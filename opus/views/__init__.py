"""Opus viewsets organised by domain."""

from .alignment import (
    AlignmentGroupViewSet,
    AlignmentMemberViewSet,
    AlignmentSetViewSet,
    AlignmentVersionViewSet,
    AlignmentViewSet,
)
from .annotations import AnnotationViewSet
from .documents import BookmarkViewSet, ExcerptViewSet, ReadingProgressViewSet
from .lexicon import GlossaryViewSet, LexicalEntryViewSet, LexicalFormViewSet
from .people import (
    AuthorAliasViewSet,
    AuthorIdentifierViewSet,
    AuthorViewSet,
    BibliographyEntryViewSet,
    WorkContributorViewSet,
)
from .planning import EditionViewSet, ShelfViewSet, SourceFileViewSet, TextUnitViewSet, WorkViewSet
from .status import ReadingView, WorkReadingProgressView

__all__ = [
    "AlignmentSetViewSet",
    "AlignmentViewSet",
    "AlignmentVersionViewSet",
    "AlignmentGroupViewSet",
    "AlignmentMemberViewSet",
    "AnnotationViewSet",
    "AuthorViewSet",
    "AuthorAliasViewSet",
    "AuthorIdentifierViewSet",
    "BibliographyEntryViewSet",
    "BookmarkViewSet",
    "ExcerptViewSet",
    "GlossaryViewSet",
    "LexicalEntryViewSet",
    "LexicalFormViewSet",
    "ReadingProgressViewSet",
    "ShelfViewSet",
    "SourceFileViewSet",
    "TextUnitViewSet",
    "EditionViewSet",
    "WorkViewSet",
    "WorkContributorViewSet",
    "ReadingView",
    "WorkReadingProgressView",
]
