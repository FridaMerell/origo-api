from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django_filters import CharFilter, FilterSet
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from opus.access import can_edit_lexical_entry, owns_work, visible_to_user
from opus.models import Glossary, LexicalEntry, LexicalForm
from opus.serializers import (
    GlossaryDetailSerializer,
    GlossaryEntrySerializer,
    GlossaryQuizSerializer,
    GlossarySerializer,
    LanguageQuizSerializer,
    LexicalEntrySerializer,
    LexicalFormSerializer,
)


def visible_entry_filter(user, entry_path=""):
    """Entries the user owns, unowned catalog entries, and entries in glossaries the user can see."""

    return (
        Q(**{f"{entry_path}owner": user})
        | Q(**{f"{entry_path}owner__isnull": True})
        | Q(**{f"{entry_path}glossaries__is_private": False})
        | Q(**{f"{entry_path}glossaries__owner": user})
    )


# What ``LexicalFormSerializer.source`` reads.
FORM_SOURCE_RELATIONS = ("unit__version__work", "unit__parent")


def with_entry_details(queryset, user):
    """Prefetch what ``LexicalEntrySerializer`` reads for each entry."""

    return queryset.prefetch_related(
        Prefetch(
            "glossaries",
            queryset=Glossary.objects.filter(owner=user),
            to_attr="request_glossaries",
        ),
        Prefetch("forms", queryset=LexicalForm.objects.select_related(*FORM_SOURCE_RELATIONS)),
    )


def visible_lexical_entries(user):
    return with_entry_details(LexicalEntry.objects.filter(visible_entry_filter(user)).distinct(), user)


class LexicalEntryFilter(FilterSet):
    search = CharFilter(method="filter_search")

    class Meta:
        model = LexicalEntry
        fields = {
            "language": ["exact"],
            "part_of_speech": ["exact"],
            "gender": ["exact"],
            "lemma": ["exact", "icontains"],
            "owner": ["exact"],
            "glossaries": ["exact"],
            # Look up the base form from a spelling variant or inflected form.
            "forms__form": ["iexact"],
        }

    def filter_search(self, queryset, name, value):
        """A word by any of its names: the lemma, a saved form, the modern form or the translation."""

        value = value.strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(lemma__icontains=value)
            | Q(forms__form__icontains=value)
            | Q(inflection_data__modern_form__icontains=value)
            | Q(translation__icontains=value)
        )


class LexicalEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LexicalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = LexicalEntryFilter

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

    @action(detail=False, methods=["get"])
    def languages(self, request):
        """The languages of the user's own words, with how many words each has."""

        rows = (
            LexicalEntry.objects.filter(owner=request.user)
            .values("language")
            .annotate(count=Count("id"))
            .order_by("language")
        )
        return Response(list(rows))

    @action(detail=False, methods=["get"])
    def quiz(self, request):
        """A random selection of the user's own words in one language for a vocabulary quiz."""

        params = LanguageQuizSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        entries = with_entry_details(
            LexicalEntry.objects.filter(owner=request.user, language=params.validated_data["language"]).order_by("?"),
            request.user,
        )[: params.validated_data["count"]]
        return Response(LexicalEntrySerializer(entries, many=True, context=self.get_serializer_context()).data)


class LexicalFormViewSet(viewsets.ModelViewSet):
    serializer_class = LexicalFormSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "entry": ["exact"],
        "form": ["exact", "iexact", "icontains"],
        "kind": ["exact"],
        "is_uncertain": ["exact"],
        "unit": ["exact"],
    }

    def get_queryset(self):
        return (
            LexicalForm.objects.filter(visible_entry_filter(self.request.user, "entry__"))
            .distinct()
            .select_related(*FORM_SOURCE_RELATIONS)
        )

    def _check_entry(self, entry):
        if not visible_lexical_entries(self.request.user).filter(pk=entry.pk).exists():
            raise ValidationError({"entry": "The entry does not exist."})
        if not can_edit_lexical_entry(entry, self.request.user):
            raise PermissionDenied("Only the entry owner can change its forms.")

    def perform_create(self, serializer):
        self._check_entry(serializer.validated_data["entry"])
        serializer.save()

    def perform_update(self, serializer):
        self._check_entry(serializer.instance.entry)
        if "entry" in serializer.validated_data:
            self._check_entry(serializer.validated_data["entry"])
        serializer.save()

    def perform_destroy(self, instance):
        self._check_entry(instance.entry)
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
        if self.action not in ("list", "quiz"):
            queryset = queryset.prefetch_related(
                Prefetch("entries", queryset=with_entry_details(LexicalEntry.objects.all(), user))
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

    @action(detail=True, methods=["get"])
    def quiz(self, request, pk=None):
        """A random selection of the glossary's words for a vocabulary quiz."""

        glossary = self.get_object()
        params = GlossaryQuizSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        entries = with_entry_details(glossary.entries.order_by("?"), request.user)[: params.validated_data["count"]]
        return Response(LexicalEntrySerializer(entries, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["delete"], url_path=r"entries/(?P<entry_id>\d+)")
    def remove_entry(self, request, pk=None, entry_id=None):
        glossary = self.get_object()
        if not owns_work(glossary, request.user):
            raise PermissionDenied("Only the glossary owner can remove words from it.")
        glossary.entries.remove(get_object_or_404(glossary.entries, pk=entry_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
