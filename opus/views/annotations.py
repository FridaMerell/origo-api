from django.db.models import Count, F, Q, TextField
from django.db.models.functions import Coalesce, Lower, Substr
from django_filters import CharFilter, FilterSet, NumberFilter
from rest_framework import permissions, viewsets

from opus.access import visible_to_user
from opus.models import Annotation
from opus.serializers import AnnotationSerializer
from origo.pagination import StandardPagination


def _target_text():
    """The annotated word or phrase as a database expression; NULL for a whole-unit annotation."""

    return Substr("unit__content", F("start_offset") + 1, F("end_offset") - F("start_offset"))


class AnnotationFilter(FilterSet):
    work = NumberFilter(field_name="unit__version__work_id")
    search = CharFilter(method="filter_search")
    ordering = CharFilter(method="filter_ordering")

    class Meta:
        model = Annotation
        fields = {
            "unit": ["exact"],
            "lexical_entry": ["exact", "isnull"],
            "target_kind": ["exact"],
            "kind": ["exact"],
        }

    def filter_search(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        return queryset.alias(target_text=_target_text()).filter(
            Q(target_text__icontains=value)
            | Q(body__icontains=value)
            | Q(lexical_entry__definition__icontains=value)
            | Q(lexical_entry__inflection_data__modern_form__icontains=value)
            | Q(lexical_entry__inflection_data__synonyms__icontains=value)
            | Q(unit__version__work__title__icontains=value)
            | Q(unit__version__title__icontains=value)
            | Q(unit__parent__label__icontains=value)
        )

    def filter_ordering(self, queryset, name, value):
        """Always ordered by work (title), so a page can be shown grouped; ``value`` orders within a work."""

        by_work = ["unit__version__work__title", "unit__version__work_id"]
        if value == "updated":
            return queryset.order_by(*by_work, "-updated_at", "id")
        if value == "alphabetical":
            return queryset.alias(
                sort_text=Lower(Coalesce(_target_text(), "unit__content", output_field=TextField()))
            ).order_by(*by_work, "sort_text", "id")
        # The order of the text: edition, chapter, paragraph, position in the paragraph.
        return queryset.order_by(
            *by_work,
            "unit__version_id",
            F("unit__parent__position").asc(nulls_first=True),
            "unit__position",
            "unit_id",
            F("start_offset").asc(nulls_first=True),
            "id",
        )


class AnnotationViewSet(viewsets.ModelViewSet):
    serializer_class = AnnotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = AnnotationFilter
    pagination_class = StandardPagination

    def get_queryset(self):
        return visible_to_user(
            Annotation.objects.filter(user=self.request.user).select_related(
                "unit__version__work", "unit__parent", "lexical_entry"
            ),
            self.request.user,
            "unit__version__work__",
        )

    def list(self, request, *args, **kwargs):
        """A page of annotations, plus what the filters of the list need to know about all of them."""

        response = super().list(request, *args, **kwargs)
        annotations = self.get_queryset().order_by()
        works = annotations.values_list("unit__version__work_id", "unit__version__work__title").distinct()
        # The counts per kind follow the chosen work, like the list itself.
        work = request.query_params.get("work")
        in_work = annotations.filter(unit__version__work_id=work) if work and work.isdigit() else annotations
        response.data["page_size"] = self.paginator.get_page_size(request)
        response.data["total"] = annotations.count()
        response.data["works"] = [
            {"id": work_id, "title": title} for work_id, title in works.order_by("unit__version__work__title")
        ]
        response.data["kinds"] = {
            row["kind"]: row["count"] for row in in_work.values("kind").annotate(count=Count("id"))
        }
        return response
