from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from django_filters import BooleanFilter, CharFilter, FilterSet, NumberFilter
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from opus.access import (
    can_edit_lexical_entry,
    editable_lexical_entries,
    own_entry_condition,
    owns_work,
    visible_entry_filter,
    visible_to_user,
    with_edit_permission,
)
from opus.models import Glossary, LexicalEntry, LexicalForm, LexicalSynonym
from opus.serializers import (
    GlossaryDetailSerializer,
    GlossaryEntrySerializer,
    GlossaryQuizSerializer,
    GlossarySerializer,
    LanguageQuizSerializer,
    LexicalEntrySerializer,
    LexicalFormSerializer,
)
from origo.pagination import StandardPagination

# What ``LexicalFormSerializer.source`` reads.
FORM_SOURCE_RELATIONS = ("unit__version__work", "unit__parent")


def marked_for_quiz(user, entry="pk"):
    """Whether ``user`` has marked the entry for quizzes, as a condition; ``entry`` is the path to it."""

    return Exists(LexicalEntry.objects.filter(pk=OuterRef(entry), quiz_users=user))


def with_entry_details(queryset, user):
    """Load what ``LexicalEntrySerializer`` reads for each entry.

    A fixed number of queries whatever the number of entries; none of it repeats a row.
    """

    return (
        with_edit_permission(queryset, user)
        .annotate(request_in_quiz=marked_for_quiz(user))
        .prefetch_related(
            Prefetch(
                "glossaries",
                queryset=Glossary.objects.filter(owner=user),
                to_attr="request_glossaries",
            ),
            Prefetch("forms", queryset=LexicalForm.objects.select_related(*FORM_SOURCE_RELATIONS)),
            Prefetch("synonyms", queryset=LexicalSynonym.objects.select_related("target")),
        )
    )


def visible_lexical_entries(user):
    return LexicalEntry.objects.filter(visible_entry_filter(user))


class LexicalEntryFilter(FilterSet):
    search = CharFilter(method="filter_search")
    # Words the user may change: their own, and unowned ones from before entries had owners.
    editable = BooleanFilter(method="filter_editable")
    # Look up the base form from a spelling variant or inflected form.
    forms__form__iexact = CharFilter(method="filter_form")
    # The words of one glossary. A word is in a glossary once, so the join repeats nothing.
    glossaries = NumberFilter(field_name="glossaries")

    class Meta:
        model = LexicalEntry
        fields = {
            "language": ["exact"],
            "part_of_speech": ["exact"],
            "gender": ["exact"],
            "lemma": ["exact", "icontains"],
            "owner": ["exact"],
        }

    def filter_search(self, queryset, name, value):
        """A word by what is written about it.

        Its lemma, saved forms, synonyms, modern form, translation, definition and connotations.
        Forms and synonyms are subqueries, so a word with several matching ones is still one row.
        """

        value = value.strip()
        if not value:
            return queryset
        forms = LexicalForm.objects.filter(entry=OuterRef("pk"), form__icontains=value)
        synonyms = LexicalSynonym.objects.filter(entry=OuterRef("pk"), text__icontains=value)
        return queryset.filter(
            Q(lemma__icontains=value)
            | Q(Exists(forms))
            | Q(Exists(synonyms))
            # Synonyms saved before they had a table of their own.
            | Q(inflection_data__synonyms__icontains=value)
            | Q(inflection_data__modern_form__icontains=value)
            | Q(translation__icontains=value)
            | Q(definition__icontains=value)
            | Q(connotations__icontains=value)
        )

    def filter_editable(self, queryset, name, value):
        return editable_lexical_entries(queryset, self.request.user) if value else queryset

    def filter_form(self, queryset, name, value):
        return queryset.filter(Exists(LexicalForm.objects.filter(entry=OuterRef("pk"), form__iexact=value)))


class LexicalEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LexicalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = LexicalEntryFilter
    # A lexicon grows without limit, so the list is always read a page at a time.
    pagination_class = StandardPagination

    def get_queryset(self):
        return with_entry_details(visible_lexical_entries(self.request.user), self.request.user)

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
        """The languages of the user's own words: how many words each has, and how many are marked for quizzes."""

        rows = (
            LexicalEntry.objects.filter(own_entry_condition(request.user))
            .values("language")
            .annotate(count=Count("id"), marked=Count("id", filter=marked_for_quiz(request.user)))
            .order_by("language")
        )
        return Response(list(rows))

    @action(detail=False, methods=["get"])
    def quiz(self, request):
        """A random selection of the user's own words in one language for a vocabulary quiz.

        With ``marked``, only among the words the user has marked for quizzes.
        """

        params = LanguageQuizSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        entries = LexicalEntry.objects.filter(
            own_entry_condition(request.user), language=params.validated_data["language"]
        )
        if params.validated_data["marked"]:
            entries = entries.filter(quiz_users=request.user)
        entries = with_entry_details(entries.order_by("?"), request.user)[: params.validated_data["count"]]
        return Response(LexicalEntrySerializer(entries, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["put", "delete"], url_path="quiz-mark")
    def quiz_mark(self, request, pk=None):
        """Mark a word for the user's own quizzes (PUT) or remove the mark (DELETE).

        Any word the user can see, since the mark is theirs and changes nothing about the word.
        """

        entry = self.get_object()
        if request.method == "PUT":
            entry.quiz_users.add(request.user)
        else:
            entry.quiz_users.remove(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LexicalFormViewSet(viewsets.ModelViewSet):
    serializer_class = LexicalFormSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "entry": ["exact"],
        "form": ["exact", "iexact", "icontains"],
        "kind": ["exact"],
        "grammatical_case": ["exact"],
        "number": ["exact"],
        "person": ["exact"],
        "tense": ["exact"],
        "mood": ["exact"],
        "voice": ["exact"],
        "degree": ["exact"],
        "definiteness": ["exact"],
        "is_uncertain": ["exact"],
        "unit": ["exact"],
    }

    def get_queryset(self):
        return (
            LexicalForm.objects.filter(visible_entry_filter(self.request.user, "entry__"))
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
        """The glossaries the user can see, with the counts the action's serializer shows."""

        user = self.request.user
        queryset = visible_to_user(Glossary.objects.all(), user)
        if self.action == "list":
            return queryset.annotate(entry_count=Count("entries"))
        if self.action in ("retrieve", "update", "partial_update"):
            return queryset.annotate(
                entry_count=Count("entries"),
                marked_count=Count("entries", filter=marked_for_quiz(user, "entries")),
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
        entries = glossary.entries.all()
        if params.validated_data["marked"]:
            entries = entries.filter(quiz_users=request.user)
        entries = with_entry_details(entries.order_by("?"), request.user)[: params.validated_data["count"]]
        return Response(LexicalEntrySerializer(entries, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["delete"], url_path=r"entries/(?P<entry_id>\d+)")
    def remove_entry(self, request, pk=None, entry_id=None):
        glossary = self.get_object()
        if not owns_work(glossary, request.user):
            raise PermissionDenied("Only the glossary owner can remove words from it.")
        glossary.entries.remove(get_object_or_404(glossary.entries, pk=entry_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
