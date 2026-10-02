"""Opus serializers organised by domain."""

from .alignment import (
    AlignmentGroupSerializer,
    AlignmentMemberSerializer,
    AlignmentSerializer,
    AlignmentSetSerializer,
    AlignmentVersionSerializer,
)
from .annotations import AnnotationSerializer
from .documents import (
    BookmarkSerializer,
    ExcerptSerializer,
    ReadingProgressOverviewSerializer,
    ReadingProgressSerializer,
)
from .lexicon import (
    GlossaryDetailSerializer,
    GlossaryEntrySerializer,
    GlossarySerializer,
    LexicalEntrySerializer,
)
from .people import (
    AuthorAliasSerializer,
    AuthorIdentifierSerializer,
    AuthorSerializer,
    BibliographyEntrySerializer,
    WorkContributorSerializer,
)
from .imports import DocumentUploadSerializer
from .planning import (
    CreateWorkWithEditionsSerializer,
    EditionSerializer,
    ShelfSerializer,
    SourceFileSerializer,
    TextUnitSerializer,
    WorkSerializer,
)

__all__ = [
    "AlignmentSerializer",
    "AlignmentGroupSerializer",
    "AlignmentMemberSerializer",
    "AlignmentSetSerializer",
    "AlignmentVersionSerializer",
    "AnnotationSerializer",
    "AuthorSerializer",
    "AuthorAliasSerializer",
    "AuthorIdentifierSerializer",
    "BibliographyEntrySerializer",
    "BookmarkSerializer",
    "ExcerptSerializer",
    "DocumentUploadSerializer",
    "GlossaryDetailSerializer",
    "GlossaryEntrySerializer",
    "GlossarySerializer",
    "LexicalEntrySerializer",
    "ReadingProgressOverviewSerializer",
    "ReadingProgressSerializer",
    "ShelfSerializer",
    "SourceFileSerializer",
    "TextUnitSerializer",
    "EditionSerializer",
    "WorkSerializer",
    "CreateWorkWithEditionsSerializer",
    "WorkContributorSerializer",
]
