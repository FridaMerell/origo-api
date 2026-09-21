from django.db.models import Q
from rest_framework import permissions, viewsets

from opus.models import Alignment, AlignmentGroup, AlignmentMember, AlignmentSet, AlignmentVersion
from opus.serializers import (
    AlignmentGroupSerializer,
    AlignmentMemberSerializer,
    AlignmentSerializer,
    AlignmentSetSerializer,
    AlignmentVersionSerializer,
)


class AlignmentSetViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentSetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"work": ["exact"], "owner": ["exact"], "is_public": ["exact"], "status": ["exact"]}

    def get_queryset(self):
        return AlignmentSet.objects.filter(Q(is_public=True) | Q(owner=self.request.user)).select_related("work", "owner")

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can edit it.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can delete it.")
        instance.delete()


class AlignmentVersionViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentVersionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"alignment_set": ["exact"], "text_version": ["exact"]}

    def get_queryset(self):
        return AlignmentVersion.objects.filter(
            Q(alignment_set__is_public=True) | Q(alignment_set__owner=self.request.user)
        ).select_related("alignment_set", "text_version__work")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add editions.")
        serializer.save()

    def perform_update(self, serializer):
        if serializer.instance.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can edit its editions.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can delete its editions.")
        instance.delete()


class AlignmentGroupViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentGroupSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"alignment_set": ["exact"], "sequence": ["exact", "gte", "lte"]}

    def get_queryset(self):
        return AlignmentGroup.objects.filter(
            Q(alignment_set__is_public=True) | Q(alignment_set__owner=self.request.user)
        ).select_related("alignment_set")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add groups.")
        serializer.save()

    def perform_update(self, serializer):
        if serializer.instance.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can edit its groups.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can delete its groups.")
        instance.delete()


class AlignmentMemberViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentMemberSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"group": ["exact"], "alignment_version": ["exact"], "status": ["exact"]}

    def get_queryset(self):
        return AlignmentMember.objects.filter(
            Q(group__alignment_set__is_public=True) | Q(group__alignment_set__owner=self.request.user)
        ).select_related("group", "alignment_version", "start_unit", "end_unit")

    def perform_create(self, serializer):
        if serializer.validated_data["group"].alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add members.")
        serializer.save()

    def perform_update(self, serializer):
        if serializer.instance.group.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can edit its members.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.group.alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can delete its members.")
        instance.delete()


class AlignmentViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "alignment_set": ["exact"],
        "source_unit": ["exact"],
        "target_unit": ["exact"],
        "alignment_type": ["exact"],
        "source_start": ["exact", "gte", "lte"],
        "source_end": ["exact", "gte", "lte"],
        "target_start": ["exact", "gte", "lte"],
        "target_end": ["exact", "gte", "lte"],
        "confidence": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return Alignment.objects.filter(
            Q(alignment_set__is_public=True) | Q(alignment_set__owner=self.request.user)
        ).select_related("alignment_set__work")
