from django.urls import include, path
from rest_framework.routers import DefaultRouter

from flux.views import (
    CodexIdentityListView,
    CodexProjectDocumentUpdateView,
    CodexProjectPlanDetailView,
    CodexProjectPlanAppendView,
    CodexProjectPlanListView,
    CodexProjectMilestoneStatusView,
    CodexProjectScaffoldView,
    CodexProjectTaskCreateView,
    CodexProjectTaskStatusView,
    DocumentViewSet,
    EntityViewSet,
    FieldViewSet,
    IntegrationViewSet,
    MilestoneViewSet,
    ProjectViewSet,
    RelationViewSet,
    ResourceViewSet,
    RolePermissionViewSet,
    RoleViewSet,
    ScreenViewSet,
    SeedRowViewSet,
    StackProfileViewSet,
    TagViewSet,
    TaskViewSet,
    TimelineView,
    UpdateViewSet,
    VisualProfileViewSet,
)

app_name = 'flux'

router = DefaultRouter()
router.register('projects', ProjectViewSet, basename='project')
router.register('milestones', MilestoneViewSet, basename='milestone')
router.register('tags', TagViewSet, basename='tag')
router.register('documents', DocumentViewSet, basename='document')
router.register('entities', EntityViewSet, basename='entity')
router.register('fields', FieldViewSet, basename='field')
router.register('relations', RelationViewSet, basename='relation')
router.register('stack-profiles', StackProfileViewSet, basename='stack-profile')
router.register('resources', ResourceViewSet, basename='resource')
router.register('roles', RoleViewSet, basename='role')
router.register('role-permissions', RolePermissionViewSet, basename='role-permission')
router.register('screens', ScreenViewSet, basename='screen')
router.register('integrations', IntegrationViewSet, basename='integration')
router.register('seed-rows', SeedRowViewSet, basename='seed-row')
router.register('identities', VisualProfileViewSet, basename='identity')
router.register('tasks', TaskViewSet, basename='task')
router.register('updates', UpdateViewSet, basename='update')

urlpatterns = [
    path('timeline/', TimelineView.as_view(), name='timeline'),
    path('codex/identities/', CodexIdentityListView.as_view(), name='codex-identity-list'),
    path('codex/projects/', CodexProjectPlanListView.as_view(), name='codex-project-list'),
    path('codex/projects/<int:project_id>/', CodexProjectPlanDetailView.as_view(), name='codex-project-detail'),
    path('codex/projects/<int:project_id>/plan/', CodexProjectPlanAppendView.as_view(), name='codex-project-plan-append'),
    path('codex/projects/<int:project_id>/scaffold/', CodexProjectScaffoldView.as_view(), name='codex-project-scaffold'),
    path('codex/projects/<int:project_id>/tasks/', CodexProjectTaskCreateView.as_view(), name='codex-project-task-create'),
    path(
        'codex/projects/<int:project_id>/tasks/<int:task_id>/status/',
        CodexProjectTaskStatusView.as_view(),
        name='codex-project-task-status',
    ),
    path(
        'codex/projects/<int:project_id>/milestones/<int:milestone_id>/status/',
        CodexProjectMilestoneStatusView.as_view(),
        name='codex-project-milestone-status',
    ),
    path(
        'codex/projects/<int:project_id>/documents/<int:document_id>/',
        CodexProjectDocumentUpdateView.as_view(),
        name='codex-project-document-update',
    ),
    path('', include(router.urls)),
]
