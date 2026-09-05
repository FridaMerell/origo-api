"""Project CRUD and the aggregate project board."""
from django.db import models
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.serializers import UserSerializer
from flux.models import Document, Milestone, Project, Task, Update
from flux.serializers import (
    DocumentSerializer,
    MilestoneSerializer,
    ProjectSerializer,
    TaskSerializer,
    UpdateSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'members']

    def get_queryset(self):
        return (
            Project.objects.filter(members=self.request.user)
            .distinct()
            .prefetch_related('members', 'milestones', 'tasks', 'updates', 'tags')
        )

    def perform_create(self, serializer):
        project = serializer.save()
        project.members.add(self.request.user)

    @action(detail=True, methods=['get'])
    def board(self, request, pk=None):
        project = self.get_object()
        projects = self.get_queryset()
        milestones = (
            Milestone.objects.filter(project=project)
            .prefetch_related('updates')
        )
        tasks = (
            Task.objects.filter(project=project)
            .select_related('project', 'milestone', 'parent', 'recurrence_source')
            .prefetch_related(
                'subtasks',
                'requirements',
                'required_by',
                'assignees',
                'updates',
            )
        )
        updates = Update.objects.filter(project=project).select_related(
            'project', 'milestone', 'task', 'author'
        )
        documents = Document.objects.filter(project=project).select_related(
            'project', 'milestone', 'task', 'author'
        )
        user_model = self.request.user.__class__
        users = user_model.objects.filter(
            models.Q(pk=request.user.pk)
            | models.Q(projects__members=request.user)
            | models.Q(tasks__project=project)
            | models.Q(updates__project=project)
        ).distinct()
        serializer_context = {'request': request}

        return Response({
            'project': ProjectSerializer(project, context=serializer_context).data,
            'projects': ProjectSerializer(
                projects, many=True, context=serializer_context
            ).data,
            'milestones': MilestoneSerializer(
                milestones, many=True, context=serializer_context
            ).data,
            'tasks': TaskSerializer(tasks, many=True, context=serializer_context).data,
            'updates': UpdateSerializer(updates, many=True, context=serializer_context).data,
            'documents': DocumentSerializer(
                documents, many=True, context=serializer_context
            ).data,
            'users': UserSerializer(users, many=True, context=serializer_context).data,
        })
