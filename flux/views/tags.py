"""Tag views."""
from django.db.models import Q, Subquery
from rest_framework import permissions, viewsets

from flux.models import Milestone, Project, Tag
from flux.serializers import TagSerializer


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'name']

    def get_queryset(self):
        project_tag_ids = Project.objects.filter(
            members=self.request.user
        ).values('tags')
        milestone_tag_ids = Milestone.objects.filter(
            project__members=self.request.user
        ).values('tags')
        queryset = Tag.objects.filter(
            Q(created_by=self.request.user)
            | Q(pk__in=Subquery(project_tag_ids))
            | Q(pk__in=Subquery(milestone_tag_ids))
        )
        if self.action in ('retrieve', 'update', 'partial_update', 'destroy'):
            return queryset.filter(created_by=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
