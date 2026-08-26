from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import CSRFTokenView, LoginView, LogoutView, MeView, UserViewSet, SelfViewSet

app_name = 'accounts'

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('self', SelfViewSet, basename='self')

urlpatterns = [
    path('csrf/', CSRFTokenView.as_view(), name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('', include(router.urls)),
]
