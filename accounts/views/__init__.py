"""Account views, organised by domain to match ``accounts.serializers``."""

from .activity import ActivityView
from .authentication import CSRFTokenView, LoginView, LogoutView, MeView
from .invitations import InvitationViewSet
from .notifications import NotificationViewSet
from .push import WebPushSubscriptionTestView, WebPushSubscriptionView
from .users import SelfViewSet, UserViewSet

__all__ = [
    "ActivityView",
    "CSRFTokenView",
    "InvitationViewSet",
    "LoginView",
    "LogoutView",
    "MeView",
    "NotificationViewSet",
    "SelfViewSet",
    "UserViewSet",
    "WebPushSubscriptionTestView",
    "WebPushSubscriptionView",
]
