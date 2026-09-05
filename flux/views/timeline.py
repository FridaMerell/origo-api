"""Aggregate timeline data across every project available to the requester."""

from django.db.models import Count, Prefetch, Q, Subquery
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import UserSerializer
from flux.models import Document, Milestone, Project, Tag, Task, Update
from flux.serializers import (
    DocumentSerializer,
    MilestoneSerializer,
    ProjectSerializer,
    TaskSerializer,
    UpdateSerializer,
)


class TimelineView(APIView):
    """Return all timeline data for projects the authenticated user can access."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        project_ids = Project.objects.filter(members=request.user).values('pk')
        user_model = request.user.__class__

        projects = Project.objects.filter(pk__in=Subquery(project_ids)).prefetch_related(
            Prefetch('members', queryset=user_model.objects.only('id')),
            Prefetch('tags', queryset=Tag.objects.only('id')),
        )
        milestones = (
            Milestone.objects.filter(project_id__in=Subquery(project_ids))
            .prefetch_related(Prefetch('tags', queryset=Tag.objects.only('id')))
            .annotate(update_count=Count('updates'))
        )
        tasks = (
            Task.objects.filter(project_id__in=Subquery(project_ids))
            .prefetch_related(
                Prefetch('subtasks', queryset=Task.objects.only('id', 'parent_id')),
                Prefetch('requirements', queryset=Task.objects.only('id')),
                Prefetch('required_by', queryset=Task.objects.only('id')),
                Prefetch('assignees', queryset=user_model.objects.only('id')),
            )
            .annotate(update_count=Count('updates'))
        )
        updates = Update.objects.filter(project_id__in=Subquery(project_ids))
        documents = Document.objects.filter(project_id__in=Subquery(project_ids))

        users = (
            user_model.objects.filter(
                Q(pk=request.user.pk)
                | Q(projects__pk__in=Subquery(project_ids))
                | Q(tasks__project_id__in=Subquery(project_ids))
                | Q(updates__project_id__in=Subquery(project_ids))
                | Q(flux_documents__project_id__in=Subquery(project_ids))
            )
            .distinct()
            .annotate(
                open_notifications=Count(
                    'notifications',
                    filter=Q(notifications__is_read=False),
                    distinct=True,
                )
            )
        )
        serializer_context = {'request': request}

        return Response({
            'projects': ProjectSerializer(projects, many=True, context=serializer_context).data,
            'milestones': MilestoneSerializer(milestones, many=True, context=serializer_context).data,
            'tasks': TaskSerializer(tasks, many=True, context=serializer_context).data,
            'updates': UpdateSerializer(updates, many=True, context=serializer_context).data,
            'documents': DocumentSerializer(documents, many=True, context=serializer_context).data,
            'users': UserSerializer(users, many=True, context=serializer_context).data,
        })
