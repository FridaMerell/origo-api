from django.urls import include, path
from rest_framework.routers import DefaultRouter

from flux.views import ProjectViewSet, TaskViewSet

app_name = 'flux'

router = DefaultRouter()
router.register('projects', ProjectViewSet, basename='project')
router.register('tasks', TaskViewSet, basename='task')

urlpatterns = [
    path('', include(router.urls)),
]
