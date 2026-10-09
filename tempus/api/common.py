from rest_framework import permissions, viewsets
from rest_framework.throttling import AnonRateThrottle


class SharedDataPermission(permissions.BasePermission):
    """Allow authenticated reads and restrict shared-data writes to staff."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.method in permissions.SAFE_METHODS or request.user.is_staff)
        )


class PublicReadThrottle(AnonRateThrottle):
    """Rate limit for the few read endpoints served without a session."""

    scope = "tempus-public-read"
    # The frontend server makes these calls on behalf of every visitor, so they
    # all arrive from one address: the limit has to cover the whole site.
    rate = "600/min"


class SharedDataViewSet(viewsets.ModelViewSet):
    permission_classes = [SharedDataPermission]
