import re
import unicodedata

from django.db import transaction
from django.db.models import Max, Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from opus.models import Alignment, AlignmentGroup, AlignmentMember, AlignmentSet, AlignmentVersion, TextUnit
from opus.serializers import (
    AlignmentGroupSerializer,
    AlignmentMemberSerializer,
    AlignmentSerializer,
    AlignmentSetSerializer,
    AlignmentVersionSerializer,
)


def visible_alignment_sets(user):
    return AlignmentSet.objects.filter(
        Q(owner=user)
        | Q(is_public=True, work__is_private=False)
        | Q(
            is_public=True,
            work__isnull=True,
            source_version__work__is_private=False,
            target_version__work__is_private=False,
        )
    )


class AlignmentSetViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentSetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"work": ["exact"], "owner": ["exact"], "is_public": ["exact"], "status": ["exact"]}

    def get_queryset(self):
        return visible_alignment_sets(self.request.user).select_related("work", "owner")

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

    @action(detail=True, methods=["post"], url_path="auto-match-chapters")
    def auto_match_chapters(self, request, pk=None):
        """Create non-destructive alignment groups from matching chapter structure."""

        with transaction.atomic():
            alignment_set = get_object_or_404(visible_alignment_sets(request.user).select_for_update(), pk=pk)
            if alignment_set.owner_id != request.user.pk:
                raise PermissionDenied("Only the alignment set owner can generate chapter matches.")
            versions = list(
                AlignmentVersion.objects.filter(alignment_set=alignment_set)
                .select_related("text_version")
                .order_by("display_order", "id")
            )
            if len(versions) < 2:
                return Response(
                    {"detail": "At least two editions are required to match chapters."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            chapters_by_version = {
                version.id: list(
                    TextUnit.objects.filter(
                        version=version.text_version,
                        kind=TextUnit.Kind.CHAPTER,
                        parent__isnull=True,
                    ).order_by("position", "id")
                )
                for version in versions
            }
            used_chapter_ids = set(
                AlignmentMember.objects.filter(
                    group__alignment_set=alignment_set,
                    start_unit__kind=TextUnit.Kind.CHAPTER,
                ).values_list("start_unit_id", flat=True)
            )
            available = {
                version_id: [
                    chapter for chapter in chapters if chapter.id not in used_chapter_ids
                ]
                for version_id, chapters in chapters_by_version.items()
            }
            candidates = self._label_matches(available)
            if not candidates and len({len(chapters) for chapters in available.values()}) == 1:
                candidates = list(zip(*(available[version.id] for version in versions)))

            next_sequence = (
                AlignmentGroup.objects.filter(alignment_set=alignment_set).aggregate(
                    maximum=Max("sequence")
                )["maximum"]
                or 0
            ) + 1
            created = []
            for chapters in candidates:
                if len(chapters) < 2:
                    continue
                label = chapters[0].label
                group = AlignmentGroup.objects.create(
                    alignment_set=alignment_set,
                    sequence=next_sequence,
                    label=label,
                )
                next_sequence += 1
                for version in versions:
                    chapter = next(
                        (item for item in chapters if item.version_id == version.text_version_id), None
                    )
                    AlignmentMember.objects.create(
                        group=group,
                        alignment_version=version,
                        start_unit=chapter,
                        end_unit=chapter,
                        status=(
                            AlignmentMember.Status.PRESENT
                            if chapter is not None
                            else AlignmentMember.Status.OMITTED
                        ),
                    )
                created.append({"id": group.id, "sequence": group.sequence, "label": group.label})

        return Response({"created_count": len(created), "groups": created})

    @staticmethod
    def _label_matches(chapters_by_version):
        """Match repeated labels by normalized text and occurrence, never by a guess."""

        indexed = {}
        for version_id, chapters in chapters_by_version.items():
            occurrences = {}
            for chapter in chapters:
                key = AlignmentSetViewSet._normalise_label(chapter.label)
                if not key:
                    continue
                occurrence = occurrences.get(key, 0)
                occurrences[key] = occurrence + 1
                indexed.setdefault((key, occurrence), {})[version_id] = chapter
        return [
            list(by_version.values())
            for _, by_version in indexed.items()
            if len(by_version) >= 2
        ]

    @staticmethod
    def _normalise_label(label):
        decomposed = unicodedata.normalize("NFKD", label.casefold())
        without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
        return re.sub(r"[^\w]+", " ", without_accents).strip()


class AlignmentVersionViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentVersionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"alignment_set": ["exact"], "text_version": ["exact"]}

    def get_queryset(self):
        return AlignmentVersion.objects.filter(
            alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("alignment_set", "text_version__work")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add editions.")
        serializer.save()

    def perform_update(self, serializer):
        target_set = serializer.validated_data.get("alignment_set", serializer.instance.alignment_set)
        if serializer.instance.alignment_set.owner_id != self.request.user.pk or target_set.owner_id != self.request.user.pk:
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
            alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("alignment_set")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add groups.")
        serializer.save()

    def perform_update(self, serializer):
        target_set = serializer.validated_data.get("alignment_set", serializer.instance.alignment_set)
        if serializer.instance.alignment_set.owner_id != self.request.user.pk or target_set.owner_id != self.request.user.pk:
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
            group__alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("group", "alignment_version", "start_unit", "end_unit")

    def perform_create(self, serializer):
        if serializer.validated_data["group"].alignment_set.owner_id != self.request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only the alignment set owner can add members.")
        serializer.save()

    def perform_update(self, serializer):
        target_group = serializer.validated_data.get("group", serializer.instance.group)
        if (
            serializer.instance.group.alignment_set.owner_id != self.request.user.pk
            or target_group.alignment_set.owner_id != self.request.user.pk
        ):
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
            alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("alignment_set__work")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can add alignments.")
        serializer.save()

    def perform_update(self, serializer):
        target_set = serializer.validated_data.get("alignment_set", serializer.instance.alignment_set)
        if serializer.instance.alignment_set.owner_id != self.request.user.pk or target_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can edit alignments.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.alignment_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can delete alignments.")
        instance.delete()
