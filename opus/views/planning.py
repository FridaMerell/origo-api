from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser
from rest_framework.response import Response

from opus.models import Annotation, Bookmark, Edition, Excerpt, Shelf, SourceFile, TextUnit, Work
from opus.access import CuratorWritePermission, owns_work, visible_to_user
from opus.serializers import (
    DocumentUploadSerializer,
    CreateWorkWithEditionsSerializer,
    SourceFileSerializer,
    ShelfSerializer,
    TextUnitSerializer,
    EditionSerializer,
    WorkSerializer,
)
from opus.services.importing import (
    DocumentImportError,
    add_empty_chapter,
    append_document,
    document_preview,
    extract_document,
    import_document,
    reorder_chapters,
)
from opus.services.importing import MAX_FILE_SIZE
from opus.services.alignment_grid import release_unit
from opus.services.pdf_notes import import_pdf_footnotes
from opus.uploads import MemoryOnlyMultiPartParser

# Larger than any real position; used to park positions while a paragraph is split.
POSITION_PARK = 1_000_000_000
# Most paragraphs one request may combine into the first.
MAX_MERGE = 50


class WorkViewSet(viewsets.ModelViewSet):
    serializer_class = WorkSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "owner": ["exact"],
        "is_private": ["exact"],
        "year": ["exact", "icontains"],
        "shelves": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_queryset(self):
        queryset = visible_to_user(
            Work.objects.prefetch_related(
                "contributors__author", "editions", "shelves"
            ),
            self.request.user,
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "editions__text_units",
                    queryset=TextUnit.objects.filter(
                        kind=TextUnit.Kind.CHAPTER, parent__isnull=True
                    ).order_by("position", "id"),
                    to_attr="request_chapters",
                )
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if not owns_work(serializer.instance, self.request.user):
            raise PermissionDenied("Only the work owner can edit it.")
        serializer.save()

    def perform_destroy(self, instance):
        if not owns_work(instance, self.request.user):
            raise PermissionDenied("Only the work owner can delete it.")
        instance.delete()

    @action(detail=False, methods=["post"], url_path="create-with-editions")
    def create_with_editions(self, request):
        serializer = CreateWorkWithEditionsSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        work = serializer.save()
        return Response(WorkSerializer(work, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ShelfViewSet(viewsets.ModelViewSet):
    queryset = Shelf.objects.all()
    serializer_class = ShelfSerializer
    permission_classes = [permissions.IsAuthenticated, CuratorWritePermission]
    filterset_fields = {"name": ["exact", "icontains"]}


class EditionViewSet(viewsets.ModelViewSet):
    serializer_class = EditionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "work": ["exact"],
        "language": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_queryset(self):
        return visible_to_user(Edition.objects.select_related("work"), self.request.user, "work__")

    def perform_create(self, serializer):
        if not owns_work(serializer.validated_data["work"], self.request.user):
            raise PermissionDenied("Only the work owner can add an edition.")
        serializer.save()

    def perform_update(self, serializer):
        target_work = serializer.validated_data.get("work", serializer.instance.work)
        if not owns_work(serializer.instance.work, self.request.user) or not owns_work(target_work, self.request.user):
            raise PermissionDenied("Only the work owner can edit an edition.")
        serializer.save()

    def perform_destroy(self, instance):
        if not owns_work(instance.work, self.request.user):
            raise PermissionDenied("Only the work owner can delete an edition.")
        instance.delete()

    @action(
        detail=True,
        methods=["post"],
        url_path="import-document",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def import_document(self, request, pk=None):
        """Extract an upload in memory and persist its paragraphs as TextUnits."""
        edition = self.get_object()
        payload, error = self._validated_upload(request)
        if error:
            return error
        uploaded_file = payload.validated_data["file"]
        label = payload.validated_data["label"]
        try:
            extracted = extract_document(uploaded_file, **payload.extract_options())
            source_file, paragraph_count = import_document(
                edition, uploaded_file, extracted=extracted, label=label
            )
        except DocumentImportError as exc:
            code = "already_imported" if "already has imported text" in str(exc) else "invalid_document"
            return self._import_error(code, str(exc))
        return self._imported(edition, uploaded_file, extracted, label, source_file, paragraph_count)

    @action(
        detail=True,
        methods=["post"],
        url_path="append-document",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def append_document(self, request, pk=None):
        """Add an upload's chapters to the edition: at the end, or before chapter ``before``."""
        edition = self.get_object()
        payload, error = self._validated_upload(request)
        if error:
            return error
        uploaded_file = payload.validated_data["file"]
        label = payload.validated_data["label"]
        before = self._chapter(edition, payload.validated_data["before"])
        try:
            extracted = extract_document(uploaded_file, **payload.extract_options())
            source_file, paragraph_count = append_document(edition, extracted=extracted, label=label, before=before)
        except DocumentImportError as exc:
            return self._import_error("invalid_document", str(exc))
        return self._imported(edition, uploaded_file, extracted, label, source_file, paragraph_count)

    @action(detail=True, methods=["post"], url_path="chapters", permission_classes=[permissions.IsAuthenticated])
    def add_chapter(self, request, pk=None):
        """Add a named chapter without text (``label``), at the end or before chapter ``before`` -
        a placeholder for one this edition lacks, so the chapters after it keep their place."""
        edition = self.get_object()
        label = str(request.data.get("label") or "").strip()
        if not label:
            raise ValidationError({"label": "A chapter name is required."})
        if len(label) > 255:
            raise ValidationError({"label": "At most 255 characters."})
        before_id = request.data.get("before")
        add_empty_chapter(edition, label, before=self._chapter(edition, before_id if before_id != "" else None))
        return Response({"chapters": self._chapters(edition)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reorder-chapters", permission_classes=[permissions.IsAuthenticated])
    def reorder_chapters(self, request, pk=None):
        """Put the edition's chapters in the order of ``chapter_ids``; their text moves with them."""
        edition = self.get_object()
        chapter_ids = request.data.get("chapter_ids")
        if not isinstance(chapter_ids, list) or not all(isinstance(value, int) for value in chapter_ids):
            raise ValidationError({"chapter_ids": "A list of chapter ids is required."})
        try:
            reorder_chapters(edition, chapter_ids)
        except DocumentImportError as exc:
            raise ValidationError({"chapter_ids": str(exc)})
        return Response({"chapters": self._chapters(edition)})

    @staticmethod
    def _chapter(edition, chapter_id):
        """The edition's top-level chapter ``chapter_id``, or ``None`` when no id is given."""
        if chapter_id is None:
            return None
        try:
            chapter_id = int(chapter_id)
        except (TypeError, ValueError):
            raise ValidationError({"before": "A chapter id is required."})
        chapter = TextUnit.objects.filter(
            pk=chapter_id, version=edition, kind=TextUnit.Kind.CHAPTER, parent__isnull=True
        ).first()
        if chapter is None:
            raise ValidationError({"before": "The chapter does not belong to this edition."})
        return chapter

    @staticmethod
    def _chapters(edition):
        return list(
            TextUnit.objects.filter(version=edition, kind=TextUnit.Kind.CHAPTER, parent__isnull=True)
            .order_by("position", "id")
            .values("id", "position", "label")
        )

    @staticmethod
    def _imported(edition, uploaded_file, extracted, label, source_file, paragraph_count):
        """The response for a completed import, after attaching a PDF's own footnotes."""
        note_result = None
        if extracted.file_type == "pdf":
            uploaded_file.seek(0)
            try:
                note_result = import_pdf_footnotes(edition, uploaded_file)
            except DocumentImportError:
                # The book's own footnote links are a bonus, not a requirement: a PDF that
                # imports fine as text but has no usable link structure shouldn't fail here.
                note_result = None
        return Response(
            {
                "source_file": SourceFileSerializer(source_file).data,
                "paragraph_count": paragraph_count,
                "chapter_count": TextUnit.objects.filter(
                    version=source_file.version, kind=TextUnit.Kind.CHAPTER
                ).count(),
                "preview": document_preview(source_file.version, extracted, label),
                "notes_created": note_result.created_count if note_result else 0,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="preview-import",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def preview_import(self, request, pk=None):
        """Preview the proposed chapter index for an edition without saving it."""
        return self._preview(request, self.get_object())

    @action(
        detail=False,
        methods=["post"],
        url_path="preview-document",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def preview_document(self, request):
        """Preview how a file would be imported before its edition exists. Nothing is saved."""
        return self._preview(request, None)

    def _preview(self, request, edition):
        payload, error = self._validated_upload(request)
        if error:
            return error
        try:
            extracted = extract_document(payload.validated_data["file"], **payload.extract_options())
        except DocumentImportError as exc:
            return self._import_error("invalid_document", str(exc))
        return Response(document_preview(edition, extracted, payload.validated_data["label"]))

    @action(
        detail=True,
        methods=["post"],
        url_path="import-pdf-notes",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def import_pdf_notes(self, request, pk=None):
        """Re-read a PDF's own footnote/commentary links and attach them as Annotations
        on the matching sentences. The edition must already have its text imported."""
        edition = self.get_object()
        if not owns_work(edition.work, self.request.user):
            raise PermissionDenied("Only the work owner can import notes for an edition.")
        payload, error = self._validated_upload(request)
        if error:
            return error
        try:
            result = import_pdf_footnotes(edition, payload.validated_data["file"])
        except DocumentImportError as exc:
            return self._import_error("invalid_document", str(exc))
        return Response(
            {
                "link_count": result.link_count,
                "matched_source_count": result.matched_source_count,
                "matched_destination_count": result.matched_destination_count,
                "created_count": result.created_count,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _validated_upload(request):
        content_length = request._request.META.get("CONTENT_LENGTH")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            return None, EditionViewSet._import_error(
                "invalid_upload", "The request has an invalid content length."
            )
        if request_size > MAX_FILE_SIZE + 1024 * 1024:
            return None, EditionViewSet._import_error(
                "file_too_large", "The document must be at most 10 MB."
            )
        try:
            payload = DocumentUploadSerializer(data=request.data)
        except ParseError:
            return None, EditionViewSet._import_error(
                "invalid_upload", "The uploaded document could not be parsed."
            )
        if not payload.is_valid():
            return None, Response(
                {
                    "detail": "The document upload is invalid.",
                    "code": "invalid_upload",
                    "errors": payload.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return payload, None

    @staticmethod
    def _import_error(code, detail):
        return Response(
            {"detail": detail, "code": code, "errors": {"file": [detail]}},
            status=status.HTTP_400_BAD_REQUEST,
        )


class SourceFileViewSet(viewsets.ModelViewSet):
    serializer_class = SourceFileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "version": ["exact"],
        "file_type": ["exact"],
        "import_status": ["exact"],
        "content_hash": ["exact"],
    }

    def get_queryset(self):
        return visible_to_user(
            SourceFile.objects.select_related("version__work"), self.request.user, "version__work__"
        )

    def perform_destroy(self, instance):
        if not owns_work(instance.version.work, self.request.user):
            raise PermissionDenied("Only the work owner can delete a source file.")
        instance.delete()

    def perform_update(self, serializer):
        target_version = serializer.validated_data.get("version", serializer.instance.version)
        if not owns_work(serializer.instance.version.work, self.request.user) or not owns_work(target_version.work, self.request.user):
            raise PermissionDenied("Only the work owner can edit a source file.")
        serializer.save()


class TextUnitViewSet(viewsets.ModelViewSet):
    serializer_class = TextUnitSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "version": ["exact"],
        "parent": ["exact", "isnull"],
        "kind": ["exact"],
        "position": ["exact", "gte", "lte"],
        "label": ["exact", "icontains"],
    }

    def get_queryset(self):
        return visible_to_user(
            TextUnit.objects.select_related("version__work", "parent"), self.request.user, "version__work__"
        )

    def perform_create(self, serializer):
        if not owns_work(serializer.validated_data["version"].work, self.request.user):
            raise PermissionDenied("Only the work owner can add text units.")
        serializer.save()

    def perform_update(self, serializer):
        target_version = serializer.validated_data.get("version", serializer.instance.version)
        if not owns_work(serializer.instance.version.work, self.request.user) or not owns_work(target_version.work, self.request.user):
            raise PermissionDenied("Only the work owner can edit text units.")
        new_content = serializer.validated_data.get("content", serializer.instance.content)
        if new_content != serializer.instance.content and serializer.instance.annotations.exists():
            # Annotation offsets refer to the exact text of this unit only.
            raise ValidationError({"content": "Remove the annotations on this paragraph before editing its text."})
        serializer.save()

    def perform_destroy(self, instance):
        if not owns_work(instance.version.work, self.request.user):
            raise PermissionDenied("Only the work owner can delete text units.")
        with transaction.atomic():
            release_unit(instance)
            instance.delete()

    @action(detail=True, methods=["post"], url_path="merge-next")
    def merge_next(self, request, pk=None):
        """Combine a paragraph with the ``count`` paragraphs that follow it in the same edition.

        The texts are joined with a single space. Annotations, bookmarks and excerpts of the
        absorbed paragraphs move to this one (annotation offsets shift with the text), and
        alignment gaps and joined cells that pointed at them are re-anchored.
        """

        unit = get_object_or_404(self.get_queryset(), pk=pk)
        if not owns_work(unit.version.work, request.user):
            raise PermissionDenied("Only the work owner can combine text units.")
        if unit.kind != TextUnit.Kind.PARAGRAPH:
            raise ValidationError({"detail": "Only paragraphs can be combined."})
        try:
            count = int(request.data.get("count", 1))
        except (TypeError, ValueError):
            raise ValidationError({"count": "An integer is required."})
        if not 1 <= count <= MAX_MERGE:
            raise ValidationError({"count": f"Must be between 1 and {MAX_MERGE}."})
        with transaction.atomic():
            unit = TextUnit.objects.select_for_update().get(pk=unit.pk)
            for _ in range(count):
                following = (
                    TextUnit.objects.select_for_update()
                    .filter(version_id=unit.version_id, kind=TextUnit.Kind.PARAGRAPH)
                    .filter(Q(position__gt=unit.position) | Q(position=unit.position, id__gt=unit.id))
                    .order_by("position", "id")
                    .first()
                )
                if following is None:
                    raise ValidationError({"detail": "There is no following paragraph to combine with."})
                shift = len(unit.content) + 1
                Annotation.objects.filter(unit=following).update(
                    unit=unit,
                    start_offset=F("start_offset") + shift,
                    end_offset=F("end_offset") + shift,
                )
                Bookmark.objects.filter(unit=following).update(unit=unit, offset=F("offset") + shift)
                Excerpt.objects.filter(unit=following).update(
                    unit=unit, start_offset=F("start_offset") + shift, end_offset=F("end_offset") + shift
                )
                release_unit(following)
                unit.content = f"{unit.content} {following.content}"
                following.delete()
            unit.save(update_fields=["content", "updated_at"])
        return Response(TextUnitSerializer(unit, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="split")
    def split(self, request, pk=None):
        """Split a paragraph in two at a character offset; later paragraphs move one position on."""

        unit = get_object_or_404(self.get_queryset(), pk=pk)
        if not owns_work(unit.version.work, request.user):
            raise PermissionDenied("Only the work owner can split text units.")
        if unit.kind != TextUnit.Kind.PARAGRAPH:
            raise ValidationError({"detail": "Only paragraphs can be split."})
        try:
            offset = int(request.data.get("offset"))
        except (TypeError, ValueError):
            raise ValidationError({"offset": "An integer is required."})
        head, tail = unit.content[:offset].rstrip(), unit.content[offset:].lstrip()
        if not head or not tail:
            raise ValidationError({"offset": "Both parts of the paragraph must contain text."})
        if unit.annotations.exists():
            raise ValidationError({"detail": "Remove the annotations on this paragraph before splitting it."})
        with transaction.atomic():
            # Positions are unique per (edition, parent): move the later ones out of the way first.
            later = TextUnit.objects.filter(
                version_id=unit.version_id, kind=TextUnit.Kind.PARAGRAPH, position__gt=unit.position
            )
            later.update(position=F("position") + POSITION_PARK)
            TextUnit.objects.filter(
                version_id=unit.version_id, kind=TextUnit.Kind.PARAGRAPH, position__gte=POSITION_PARK
            ).update(position=F("position") - POSITION_PARK + 1)
            created = TextUnit.objects.create(
                version_id=unit.version_id,
                parent_id=unit.parent_id,
                kind=TextUnit.Kind.PARAGRAPH,
                position=unit.position + 1,
                content=tail,
            )
            unit.content = head
            unit.save(update_fields=["content", "updated_at"])
        context = self.get_serializer_context()
        return Response(
            {
                "units": [
                    TextUnitSerializer(unit, context=context).data,
                    TextUnitSerializer(created, context=context).data,
                ]
            },
            status=status.HTTP_201_CREATED,
        )
