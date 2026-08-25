from django.urls import include, path
from rest_framework.routers import DefaultRouter

from flux.views import MilestoneViewSet, ProjectViewSet, TaskViewSet, UpdateViewSet

app_name = 'flux'

router = DefaultRouter()
router.register('projects', ProjectViewSet, basename='project')
router.register('milestones', MilestoneViewSet, basename='milestone')
router.register('tasks', TaskViewSet, basename='task')
router.register('updates', UpdateViewSet, basename='update')

urlpatterns = [
    path('', include(router.urls)),
]
