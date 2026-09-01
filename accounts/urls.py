from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from accounts.views import (
    CSRFTokenView,
    InvitationViewSet,
    LoginView,
    LogoutView,
    MeView,
    NotificationViewSet,
    SelfViewSet,
    UserViewSet,
)

app_name = 'accounts'

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('self', SelfViewSet, basename='self')
router.register('notifications', NotificationViewSet, basename='notification')
router.register('invitations', InvitationViewSet, basename='invitation')

urlpatterns = [
    path('csrf/', CSRFTokenView.as_view(), name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/', obtain_auth_token, name='token'),
    path('me/', MeView.as_view(), name='me'),
    path('', include(router.urls)),
]
