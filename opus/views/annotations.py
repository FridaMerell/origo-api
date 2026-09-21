from rest_framework import permissions, viewsets

from opus.access import visible_to_user
from opus.models import Annotation
from opus.serializers import AnnotationSerializer


class AnnotationViewSet(viewsets.ModelViewSet):
    serializer_class = AnnotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "unit": ["exact"],
        "lexical_entry": ["exact", "isnull"],
        "kind": ["exact"],
    }

    def get_queryset(self):
        return visible_to_user(
            Annotation.objects.filter(user=self.request.user).select_related("unit__version__work"),
            self.request.user,
            "unit__version__work__",
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
