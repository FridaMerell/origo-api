"""Shareable invite links for Verso houses and Flux projects."""
from django.contrib.auth import login
from django.db.models import Q
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Invitation
from accounts.serializers import InvitationRedeemSerializer, InvitationSerializer


class InvitationViewSet(mixins.CreateModelMixin,
                        mixins.ListModelMixin,
                        mixins.RetrieveModelMixin,
                        mixins.DestroyModelMixin,
                        viewsets.GenericViewSet):
    """Shareable invite links that let people join a Verso house or Flux project.

    Set exactly one of ``house`` / ``project`` on create; the response carries
    the ``token`` plaintext exactly once -- build the invite link from it.
    ``DELETE`` (or ``POST .../revoke/``) revokes an invitation without removing
    the row. ``POST .../redeem/`` is open: an authenticated caller joins the
    group directly; an anonymous caller must also send ``username``/``password``
    (and optional ``email``) to create an account and is logged in on success.
    """

    serializer_class = InvitationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'project']

    def get_queryset(self):
        user = self.request.user
        return Invitation.objects.filter(
            Q(house__members=user)
            | Q(project__members=user)
            | Q(house__isnull=True, project__isnull=True, created_by=user)
        ).select_related('house', 'project').distinct()

    def perform_destroy(self, instance):
        instance.revoke()

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        invitation = self.get_object()
        invitation.revoke()
        serializer = self.get_serializer(invitation)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[permissions.AllowAny],
    )
    def redeem(self, request):
        serializer = InvitationRedeemSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        user, invitation, created = serializer.save()
        if created:
            login(
                request, user,
                backend='django.contrib.auth.backends.ModelBackend',
            )
        group = invitation.target
        return Response({
            'target_kind': invitation.target_kind,
            'target': {'id': group.pk, 'name': group.name} if group else None,
            'created': created,
        })
