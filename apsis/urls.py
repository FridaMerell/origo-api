from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter
from apsis.views import PostViewSet, place_detail, place_search, place_summaries
router = DefaultRouter()
router.register(r'posts', PostViewSet)

urlpatterns = [
    path('places/', place_search),
    path('places/summaries/', place_summaries),
    re_path(r'^places/(?P<place_id>[0-9A-Za-z-]+)/$', place_detail),
    path('', include(router.urls)),
]
