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
from .lexicon import LexicalEntryViewSet
from .planning import EditionViewSet, ShelfViewSet, SourceFileViewSet, TextUnitViewSet, WorkViewSet
from .status import ReadingStatusView

__all__ = [
    "AlignmentSetViewSet",
    "AlignmentViewSet",
    "AlignmentVersionViewSet",
    "AlignmentGroupViewSet",
    "AlignmentMemberViewSet",
    "AnnotationViewSet",
    "BookmarkViewSet",
    "ExcerptViewSet",
    "LexicalEntryViewSet",
    "ReadingProgressViewSet",
    "ShelfViewSet",
    "SourceFileViewSet",
    "TextUnitViewSet",
    "EditionViewSet",
    "WorkViewSet",
    "ReadingStatusView",
]
