from rest_framework import permissions, viewsets
from django_filters import FilterSet, NumberFilter

from opus.access import visible_to_user
from opus.models import Annotation
from opus.serializers import AnnotationSerializer


class AnnotationFilter(FilterSet):
    work = NumberFilter(field_name="unit__version__work_id")

    class Meta:
        model = Annotation
        fields = {
            "unit": ["exact"],
            "lexical_entry": ["exact", "isnull"],
            "target_kind": ["exact"],
            "kind": ["exact"],
        }


class AnnotationViewSet(viewsets.ModelViewSet):
    serializer_class = AnnotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = AnnotationFilter

    def get_queryset(self):
        return visible_to_user(
            Annotation.objects.filter(user=self.request.user).select_related("unit__version__work"),
            self.request.user,
            "unit__version__work__",
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
