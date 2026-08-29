from django.urls import include, path
from rest_framework.routers import DefaultRouter
from apsis.views import PostViewSet
router = DefaultRouter()
router.register(r'posts', PostViewSet)

urlpatterns = [
    path('', include(router.urls)),
]

