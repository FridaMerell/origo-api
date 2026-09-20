"""Project CRUD and the aggregate project board."""
from django.http import Http404
from django.db.models import Count, Prefetch, Q, Subquery
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.serializers import UserSerializer
from flux.models import Document, Milestone, Project, Tag, Task, Update
from flux.serializers import (
    DocumentSerializer,
    MilestoneSerializer,
    ProjectSerializer,
    TaskSerializer,
    UpdateSerializer,
)
from flux.services.planning import generate_tasks
from flux.services.scaffold import ScaffoldError, generate_files
from flux.services.scaffold.spec import build_spec


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'members']

    def get_queryset(self):
        queryset = Project.objects.filter(members=self.request.user)
        if self.action in ('list', 'retrieve', 'board'):
            user_model = self.request.user.__class__
            return queryset.prefetch_related(
                Prefetch('members', queryset=user_model.objects.only('id')),
                Prefetch('tags', queryset=Tag.objects.only('id')),
            )
        return queryset

    def perform_create(self, serializer):
        project = serializer.save()
        project.members.add(self.request.user)

    @action(detail=True, methods=['get'])
    def scaffold(self, request, pk=None):
        target = request.query_params.get('target', '')
        try:
            files = generate_files(build_spec(self.get_object()), target)
        except ScaffoldError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'target': target, 'files': files})

    @action(detail=True, methods=['post'], url_path='scaffold-document')
    def scaffold_document(self, request, pk=None):
        project = self.get_object()
        target = request.data.get('target', '')
        try:
            files = generate_files(build_spec(project), target)
        except ScaffoldError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        content = '\n\n'.join(f'## `{item["path"]}`\n\n````\n{item["content"]}````' for item in files)
        title = f'Scaffold: {target}'
        document = Document.objects.filter(project=project, title=title).order_by('id').first()
        if document is None:
            document = Document(project=project, title=title)
        document.kind = Document.Kind.MARKDOWN
        document.content = content
        document.author = request.user
        document.save()
        return Response(DocumentSerializer(document, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='generate-tasks')
    def generate_project_tasks(self, request, pk=None):
        created = generate_tasks(self.get_object())
        return Response(
            {'created': [{'id': task.id, 'title': task.title, 'milestone': task.milestone_id} for task in created]},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def board(self, request, pk=None):
        projects = list(self.get_queryset())
        project = next(
            (candidate for candidate in projects if str(candidate.pk) == str(pk)),
            None,
        )
        if project is None:
            raise Http404
        milestones = (
            Milestone.objects.filter(project=project)
            .prefetch_related(
                Prefetch('tags', queryset=Tag.objects.only('id'))
            )
            .annotate(update_count=Count('updates'))
        )
        tasks = (
            Task.objects.filter(project=project)
            .prefetch_related(
                Prefetch(
                    'subtasks',
                    queryset=Task.objects.only('id', 'parent_id'),
                ),
                Prefetch('requirements', queryset=Task.objects.only('id')),
                Prefetch('required_by', queryset=Task.objects.only('id')),
                Prefetch(
                    'assignees',
                    queryset=self.request.user.__class__.objects.only('id'),
                ),
            )
            .annotate(update_count=Count('updates'))
        )
        updates = Update.objects.filter(project=project)
        documents = Document.objects.filter(project=project)
        user_model = self.request.user.__class__
        collaborator_ids = user_model.objects.filter(
            projects__members=request.user
        ).values('pk')
        assignee_ids = Task.objects.filter(project=project).values('assignees')
        author_ids = Update.objects.filter(project=project).values('author')
        users = user_model.objects.filter(
            Q(pk=request.user.pk)
            | Q(pk__in=Subquery(collaborator_ids))
            | Q(pk__in=Subquery(assignee_ids))
            | Q(pk__in=Subquery(author_ids))
        ).annotate(
            open_notifications=Count(
                'notifications',
                filter=Q(notifications__is_read=False),
                distinct=True,
            )
        )
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
