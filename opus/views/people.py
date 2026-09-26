"""CRUD APIs for people connected to literary works."""

from django.db.models import Q
from rest_framework import permissions, viewsets

from opus.models import Author, AuthorAlias, AuthorIdentifier, BibliographyEntry, WorkContributor
from opus.serializers import (
    AuthorAliasSerializer,
    AuthorIdentifierSerializer,
    AuthorSerializer,
    BibliographyEntrySerializer,
    WorkContributorSerializer,
)
from opus.access import CuratorWritePermission, owns_work
from rest_framework.exceptions import PermissionDenied


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    permission_classes = [permissions.IsAuthenticated, CuratorWritePermission]
    filterset_fields = {
        "name": ["exact", "icontains"],
        "born": ["exact", "icontains"],
        "died": ["exact", "icontains"],
    }


class AuthorAliasViewSet(viewsets.ModelViewSet):
    queryset = AuthorAlias.objects.select_related("author")
    serializer_class = AuthorAliasSerializer
    permission_classes = [permissions.IsAuthenticated, CuratorWritePermission]
    filterset_fields = {
        "author": ["exact"],
        "name": ["exact", "icontains"],
        "language": ["exact"],
        "is_preferred": ["exact"],
    }


class AuthorIdentifierViewSet(viewsets.ModelViewSet):
    queryset = AuthorIdentifier.objects.select_related("author")
    serializer_class = AuthorIdentifierSerializer
    permission_classes = [permissions.IsAuthenticated, CuratorWritePermission]
    filterset_fields = {
        "author": ["exact"],
        "provider": ["exact"],
        "external_id": ["exact"],
    }


class BibliographyEntryViewSet(viewsets.ModelViewSet):
    serializer_class = BibliographyEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "author": ["exact"],
        "work": ["exact", "isnull"],
        "year": ["exact", "icontains"],
        "language": ["exact"],
        "external_provider": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_queryset(self):
        return BibliographyEntry.objects.select_related("author", "work").filter(
            Q(work__isnull=True) | Q(work__is_private=False) | Q(work__owner=self.request.user)
        )

    def _can_write(self, entry):
        return self.request.user.is_staff or (
            entry.work_id is not None and owns_work(entry.work, self.request.user)
        )

    def perform_create(self, serializer):
        work = serializer.validated_data.get("work")
        if not self.request.user.is_staff and (work is None or not owns_work(work, self.request.user)):
            raise PermissionDenied("Only a curator or the work owner can add this bibliography entry.")
        serializer.save()

    def perform_update(self, serializer):
        target_work = serializer.validated_data.get("work", serializer.instance.work)
        if not self._can_write(serializer.instance) or (
            target_work is not None and not self.request.user.is_staff and not owns_work(target_work, self.request.user)
        ):
            raise PermissionDenied("Only a curator or the work owner can edit this bibliography entry.")
        serializer.save()

    def perform_destroy(self, instance):
        if not self._can_write(instance):
            raise PermissionDenied("Only a curator or the work owner can delete this bibliography entry.")
        instance.delete()


class WorkContributorViewSet(viewsets.ModelViewSet):
    serializer_class = WorkContributorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"work": ["exact"], "author": ["exact"], "role": ["exact"]}

    def get_queryset(self):
        return WorkContributor.objects.select_related("work", "author").filter(
            Q(work__is_private=False) | Q(work__owner=self.request.user)
        )

    def perform_create(self, serializer):
        if not owns_work(serializer.validated_data["work"], self.request.user):
            raise PermissionDenied("Only the work owner can add contributors.")
        serializer.save()

    def perform_update(self, serializer):
        target_work = serializer.validated_data.get("work", serializer.instance.work)
        if not owns_work(serializer.instance.work, self.request.user) or not owns_work(target_work, self.request.user):
            raise PermissionDenied("Only the work owner can edit contributors.")
        serializer.save()

    def perform_destroy(self, instance):
        if not owns_work(instance.work, self.request.user):
            raise PermissionDenied("Only the work owner can delete contributors.")
        instance.delete()
