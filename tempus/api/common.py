from rest_framework import permissions, viewsets


class SharedDataPermission(permissions.BasePermission):
    """Allow authenticated reads and restrict shared-data writes to staff."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.method in permissions.SAFE_METHODS or request.user.is_staff)
        )


class SharedDataViewSet(viewsets.ModelViewSet):
    permission_classes = [SharedDataPermission]
