from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.parsers import FormParser
from rest_framework.response import Response

from opus.models import Edition, Shelf, SourceFile, TextUnit, Work
from opus.access import visible_to_user
from opus.serializers import (
    DocumentUploadSerializer,
    CreateWorkWithEditionsSerializer,
    SourceFileSerializer,
    ShelfSerializer,
    TextUnitSerializer,
    EditionSerializer,
    WorkSerializer,
)
from opus.services.importing import DocumentImportError, import_document
from opus.services.importing import MAX_FILE_SIZE
from opus.uploads import MemoryOnlyMultiPartParser


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
        return visible_to_user(
            Work.objects.prefetch_related(
                "contributors__author", "editions", "shelves"
            ),
            self.request.user,
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

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
    permission_classes = [permissions.IsAuthenticated]
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

    @action(
        detail=True,
        methods=["post"],
        url_path="import-document",
        parser_classes=[MemoryOnlyMultiPartParser, FormParser],
        permission_classes=[permissions.IsAuthenticated],
    )
    def import_document(self, request, pk=None):
        """Extract an upload in memory and persist its paragraphs as TextUnits."""

        content_length = request._request.META.get("CONTENT_LENGTH")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            return self._import_error("invalid_upload", "The request has an invalid content length.")
        if request_size > MAX_FILE_SIZE + 1024 * 1024:
            return self._import_error("file_too_large", "The document must be at most 10 MB.")
        try:
            payload = DocumentUploadSerializer(data=request.data)
        except ParseError:
            return self._import_error("invalid_upload", "The uploaded document could not be parsed.")
        if not payload.is_valid():
            return Response(
                {
                    "detail": "The document upload is invalid.",
                    "code": "invalid_upload",
                    "errors": payload.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            source_file, paragraph_count = import_document(
                self.get_object(), payload.validated_data["file"]
            )
        except DocumentImportError as exc:
            code = "already_imported" if "already has imported text" in str(exc) else "invalid_document"
            return self._import_error(code, str(exc))
        return Response(
            {
                "source_file": SourceFileSerializer(source_file).data,
                "paragraph_count": paragraph_count,
            },
            status=status.HTTP_201_CREATED,
        )

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
            TextUnit.objects.select_related("version__work"), self.request.user, "version__work__"
        )
