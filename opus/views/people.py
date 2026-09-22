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


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "name": ["exact", "icontains"],
        "born": ["exact", "icontains"],
        "died": ["exact", "icontains"],
    }


class AuthorAliasViewSet(viewsets.ModelViewSet):
    queryset = AuthorAlias.objects.select_related("author")
    serializer_class = AuthorAliasSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "author": ["exact"],
        "name": ["exact", "icontains"],
        "language": ["exact"],
        "is_preferred": ["exact"],
    }


class AuthorIdentifierViewSet(viewsets.ModelViewSet):
    queryset = AuthorIdentifier.objects.select_related("author")
    serializer_class = AuthorIdentifierSerializer
    permission_classes = [permissions.IsAuthenticated]
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


class WorkContributorViewSet(viewsets.ModelViewSet):
    serializer_class = WorkContributorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"work": ["exact"], "author": ["exact"], "role": ["exact"]}

    def get_queryset(self):
        return WorkContributor.objects.select_related("work", "author").filter(
            Q(work__is_private=False) | Q(work__owner=self.request.user)
        )
