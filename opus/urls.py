from django.urls import include, path
from rest_framework.routers import DefaultRouter

from opus.views import (
    AlignmentGroupViewSet,
    AlignmentMemberViewSet,
    AlignmentSetViewSet,
    AlignmentViewSet,
    AlignmentVersionViewSet,
    AnnotationViewSet,
    AuthorAliasViewSet,
    AuthorIdentifierViewSet,
    AuthorViewSet,
    BibliographyEntryViewSet,
    BookmarkViewSet,
    ExcerptViewSet,
    LexicalEntryViewSet,
    ReadingProgressViewSet,
    SourceFileViewSet,
    ReadingStatusView,
    ShelfViewSet,
    TextUnitViewSet,
    EditionViewSet,
    WorkViewSet,
    WorkContributorViewSet,
)

app_name = "opus"

router = DefaultRouter()
router.register("alignment-sets", AlignmentSetViewSet, basename="alignment-set")
router.register("alignments", AlignmentViewSet, basename="alignment")
router.register("alignment-versions", AlignmentVersionViewSet, basename="alignment-version")
router.register("alignment-groups", AlignmentGroupViewSet, basename="alignment-group")
router.register("alignment-members", AlignmentMemberViewSet, basename="alignment-member")
router.register("annotations", AnnotationViewSet, basename="annotation")
router.register("authors", AuthorViewSet, basename="author")
router.register("author-aliases", AuthorAliasViewSet, basename="author-alias")
router.register("author-identifiers", AuthorIdentifierViewSet, basename="author-identifier")
router.register("bibliography-entries", BibliographyEntryViewSet, basename="bibliography-entry")
router.register("bookmarks", BookmarkViewSet, basename="bookmark")
router.register("excerpts", ExcerptViewSet, basename="excerpt")
router.register("lexical-entries", LexicalEntryViewSet, basename="lexical-entry")
router.register("reading-progress", ReadingProgressViewSet, basename="reading-progress")
router.register("shelves", ShelfViewSet, basename="shelf")
router.register("source-files", SourceFileViewSet, basename="source-file")
router.register("text-units", TextUnitViewSet, basename="text-unit")
router.register("editions", EditionViewSet, basename="edition")
router.register("works", WorkViewSet, basename="work")
router.register("work-contributors", WorkContributorViewSet, basename="work-contributor")

urlpatterns = [
    path("status/", ReadingStatusView.as_view(), name="reading-status"),
    path("", include(router.urls)),
]
