from django.urls import include, path
from rest_framework.routers import DefaultRouter

from flux.views import (
    CodexProjectPlanDetailView,
    CodexProjectPlanListView,
    MilestoneViewSet,
    ProjectViewSet,
    TaskViewSet,
    UpdateViewSet,
)

app_name = 'flux'

router = DefaultRouter()
router.register('projects', ProjectViewSet, basename='project')
router.register('milestones', MilestoneViewSet, basename='milestone')
router.register('tasks', TaskViewSet, basename='task')
router.register('updates', UpdateViewSet, basename='update')

urlpatterns = [
    path('codex/projects/', CodexProjectPlanListView.as_view(), name='codex-project-list'),
    path('codex/projects/<int:project_id>/', CodexProjectPlanDetailView.as_view(), name='codex-project-detail'),
    path('', include(router.urls)),
]
