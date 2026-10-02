from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from opus.access import can_edit_lexical_entry, owns_work, visible_to_user
from opus.models import Glossary, LexicalEntry
from opus.serializers import (
    GlossaryDetailSerializer,
    GlossaryEntrySerializer,
    GlossarySerializer,
    LexicalEntrySerializer,
)


def visible_lexical_entries(user):
    """Entries the user owns, unowned catalog entries, and entries in glossaries the user can see."""

    return (
        LexicalEntry.objects.filter(
            Q(owner=user)
            | Q(owner__isnull=True)
            | Q(glossaries__is_private=False)
            | Q(glossaries__owner=user)
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "glossaries",
                queryset=Glossary.objects.filter(owner=user),
                to_attr="request_glossaries",
            )
        )
    )


class LexicalEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LexicalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "language": ["exact"],
        "part_of_speech": ["exact"],
        "gender": ["exact"],
        "lemma": ["exact", "icontains"],
        "owner": ["exact"],
        "glossaries": ["exact"],
    }

    def get_queryset(self):
        return visible_lexical_entries(self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        entry = serializer.instance
        user = self.request.user
        if not can_edit_lexical_entry(entry, user):
            raise PermissionDenied("Only the entry owner can edit it.")
        if entry.owner_id is None and not user.is_staff:
            serializer.save(owner=user)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        if not can_edit_lexical_entry(instance, self.request.user):
            raise PermissionDenied("Only the entry owner can delete it.")
        instance.delete()


class GlossaryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "owner": ["exact"],
        "is_private": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_serializer_class(self):
        return GlossarySerializer if self.action == "list" else GlossaryDetailSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = visible_to_user(Glossary.objects.all(), user).annotate(
            entry_count=Count("entries", distinct=True)
        )
        if self.action != "list":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "entries",
                    queryset=LexicalEntry.objects.prefetch_related(
                        Prefetch(
                            "glossaries",
                            queryset=Glossary.objects.filter(owner=user),
                            to_attr="request_glossaries",
                        )
                    ),
                )
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if not owns_work(serializer.instance, self.request.user):
            raise PermissionDenied("Only the glossary owner can edit it.")
        serializer.save()

    def perform_destroy(self, instance):
        if not owns_work(instance, self.request.user):
            raise PermissionDenied("Only the glossary owner can delete it.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="entries")
    def add_entry(self, request, pk=None):
        glossary = self.get_object()
        if not owns_work(glossary, request.user):
            raise PermissionDenied("Only the glossary owner can add words to it.")
        serializer = GlossaryEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.validated_data["lexical_entry"]
        if not visible_lexical_entries(request.user).filter(pk=entry.pk).exists():
            raise ValidationError({"lexical_entry": "The entry does not exist."})
        glossary.entries.add(entry)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["delete"], url_path=r"entries/(?P<entry_id>\d+)")
    def remove_entry(self, request, pk=None, entry_id=None):
        glossary = self.get_object()
        if not owns_work(glossary, request.user):
            raise PermissionDenied("Only the glossary owner can remove words from it.")
        glossary.entries.remove(get_object_or_404(glossary.entries, pk=entry_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
