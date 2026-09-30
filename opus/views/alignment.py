import re
import unicodedata

from django.db import transaction
from django.db.models import Q
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from opus.models import (
    Alignment,
    AlignmentGroup,
    AlignmentMember,
    AlignmentSet,
    AlignmentVersion,
    Annotation,
    ReadingProgress,
    TextUnit,
)
from opus.serializers import (
    AlignmentGroupSerializer,
    AlignmentMemberSerializer,
    AlignmentSerializer,
    AlignmentSetSerializer,
    AlignmentVersionSerializer,
)
from opus.services.alignment_grid import GAP, Grid, GridError, reset as reset_alignment
from .status import reading_unit_payload

DEFAULT_WINDOW = 10
MAX_WINDOW = 500


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


def lock_owned_alignment_set(user, pk):
    """Lock one alignment set for editing; only its owner may do so.

    ``of=("self",)`` is required: the visibility filter joins nullable relations, and
    PostgreSQL refuses ``FOR UPDATE`` on the nullable side of an outer join.
    """

    alignment_set = get_object_or_404(visible_alignment_sets(user).select_for_update(of=("self",)), pk=pk)
    if alignment_set.owner_id != user.pk:
        raise PermissionDenied("Only the alignment set owner can edit it.")
    return alignment_set


def _int(data, key, default=None, minimum=None, maximum=None):
    value = data.get(key)
    if value is None or value == "":
        if default is None:
            raise ValidationError({key: "This field is required."})
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError({key: "An integer is required."})
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _window(data):
    return (
        _int(data, "offset", default=0, minimum=0),
        _int(data, "limit", default=DEFAULT_WINDOW, minimum=1, maximum=MAX_WINDOW),
    )


def alignment_matrix_payload(alignment_set, user, offset=0, limit=DEFAULT_WINDOW):
    """Rows ``offset .. offset + limit`` of the grid, one cell per edition.

    A cell is ``{alignment_version, kind, units}``: ``text`` (one or more paragraphs), ``gap``
    (an empty cell inside the edition) or ``end`` (the edition has no more paragraphs).
    """

    grid = Grid(alignment_set)
    total_rows = grid.total_rows
    rows_range = range(offset, min(offset + limit, total_rows))

    wanted = {}
    for column in grid.columns:
        for row in rows_range:
            if row < len(column.cells):
                wanted[(column.version.id, row)] = column.unit_ids(column.cells[row])
    unit_ids = {unit_id for ids in wanted.values() for unit_id in ids}
    units = {unit.id: unit for unit in TextUnit.objects.filter(id__in=unit_ids).select_related("parent")}
    annotations = {}
    for annotation in (
        Annotation.objects.filter(user=user, unit_id__in=unit_ids)
        .select_related("lexical_entry")
        .order_by("start_offset", "id")
    ):
        annotations.setdefault(annotation.unit_id, []).append(annotation)
    for unit in units.values():
        unit.request_annotations = annotations.get(unit.id, [])

    rows = []
    for row in rows_range:
        cells = []
        for column in grid.columns:
            if row >= len(column.cells):
                kind, ids = "end", []
            else:
                cell = column.cells[row]
                kind, ids = ("gap" if cell[0] == GAP else "text"), wanted[(column.version.id, row)]
            cells.append(
                {
                    "alignment_version": column.version.id,
                    "kind": kind,
                    "units": [reading_unit_payload(units[unit_id]) for unit_id in ids],
                }
            )
        rows.append({"row": row, "cells": cells})

    return {
        "set": AlignmentSetSerializer(alignment_set).data,
        "versions": AlignmentVersionSerializer([column.version for column in grid.columns], many=True).data,
        "total_rows": total_rows,
        "offset": offset,
        "has_more": offset + limit < total_rows,
        "rows": rows,
    }


def _normalise_label(label):
    decomposed = unicodedata.normalize("NFKD", label.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", " ", without_accents).strip()


def _label_matches(chapters_by_version):
    """Match repeated chapter labels by normalised text and occurrence, never by a guess."""

    indexed = {}
    for version_id, chapters in chapters_by_version.items():
        occurrences = {}
        for chapter in chapters:
            key = _normalise_label(chapter.label)
            if not key:
                continue
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            indexed.setdefault((key, occurrence), {})[version_id] = chapter.id
    return [by_version for by_version in indexed.values() if len(by_version) >= 2]


class AlignmentSetViewSet(viewsets.ModelViewSet):
    serializer_class = AlignmentSetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"work": ["exact"], "owner": ["exact"], "is_public": ["exact"], "status": ["exact"]}

    def get_queryset(self):
        return visible_alignment_sets(self.request.user).select_related("work", "owner")

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can edit it.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can delete it.")
        instance.delete()

    # -- reading ---------------------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="matrix")
    def matrix(self, request, pk=None):
        """The parallel-reading grid: rows of per-edition cells, windowed by ``offset``/``limit``."""

        alignment_set = get_object_or_404(self.get_queryset(), pk=pk)
        offset, limit = _window(request.query_params)
        focus_row = None
        unit_param = request.query_params.get("unit")
        if unit_param:
            # Jump to a specific paragraph or chapter (e.g. from an edition's chapter index),
            # in whichever edition it belongs to. Silently ignored if it doesn't resolve to a
            # cell in this set, so a stale link just falls back to the requested window.
            unit_id = _int(request.query_params, "unit")
            edition_id = TextUnit.objects.filter(pk=unit_id).values_list("version_id", flat=True).first()
            grid = Grid(alignment_set)
            column = next((c for c in grid.columns if c.version.text_version_id == edition_id), None)
            if column is not None:
                focus_row = grid.row_for_unit(column.version.id, unit_id)
                if focus_row is not None:
                    offset = max(0, focus_row - 3)
        elif request.query_params.get("focus") == "reading" and alignment_set.work_id:
            # Open where the user last was: the row of their saved reading position.
            progress = ReadingProgress.objects.filter(user=request.user, work_id=alignment_set.work_id).first()
            if progress is not None:
                focus_row = Grid(alignment_set).row_at_position(progress.position)
                if focus_row is not None:
                    offset = max(0, focus_row - 3)  # a little context above the row itself
        payload = alignment_matrix_payload(alignment_set, request.user, offset, limit)
        if focus_row is not None:
            payload["focus_row"] = focus_row
        return Response(payload)

    # -- editing (owner only, atomic; every edit returns the refreshed window) --------------

    def _edit(self, request, pk, change):
        offset, limit = _window(request.data)
        with transaction.atomic():
            alignment_set = lock_owned_alignment_set(request.user, pk)
            try:
                result = change(Grid(alignment_set), alignment_set)
            except GridError as exc:
                raise ValidationError({"detail": str(exc)})
            if result and "row" in result:
                offset = result["row"] - result["row"] % limit  # the page that holds what was just aligned
            payload = alignment_matrix_payload(alignment_set, request.user, offset, limit)
        if result is not None:
            payload["result"] = result
        return Response(payload)

    def _cell(self, request):
        return _int(request.data, "alignment_version"), _int(request.data, "row", minimum=0)

    @action(detail=True, methods=["post"], url_path="shift")
    def shift(self, request, pk=None):
        """Insert a gap at a row (``insert_gap``) or remove the gap there (``remove_gap``) in one edition."""

        version_id, row = self._cell(request)
        operation = request.data.get("action")
        if operation not in ("insert_gap", "remove_gap"):
            raise ValidationError({"action": "Must be 'insert_gap' or 'remove_gap'."})
        return self._edit(request, pk, lambda grid, _set: getattr(grid, operation)(version_id, row))

    @action(detail=True, methods=["post"], url_path="join")
    def join(self, request, pk=None):
        """Join the cell at a row with the one below it in one edition."""

        version_id, row = self._cell(request)
        return self._edit(request, pk, lambda grid, _set: grid.join_next(version_id, row))

    @action(detail=True, methods=["post"], url_path="split")
    def split(self, request, pk=None):
        """Split the last paragraph off the joined cell at a row in one edition."""

        version_id, row = self._cell(request)
        return self._edit(request, pk, lambda grid, _set: grid.split_last(version_id, row))

    @action(detail=True, methods=["post"], url_path="align")
    def align(self, request, pk=None):
        """Line up chapters (or paragraphs) from several editions on shared rows.

        ``groups`` is a list of groups, each a list of ``{alignment_version, unit}`` with one
        item per edition (``items`` is shorthand for a single group). With ``dry_run`` the
        response only carries the plan in ``result`` — nothing is saved and the window is not
        moved.
        """

        raw_groups = request.data.get("groups")
        if raw_groups is None and request.data.get("items") is not None:
            raw_groups = [request.data.get("items")]
        if not isinstance(raw_groups, list) or not raw_groups:
            raise ValidationError({"groups": "Give at least one group of {alignment_version, unit} items."})
        groups = []
        for raw in raw_groups:
            if not isinstance(raw, list) or len(raw) < 2 or not all(isinstance(item, dict) for item in raw):
                raise ValidationError({"groups": "Each group needs at least two {alignment_version, unit} items."})
            groups.append([(_int(item, "alignment_version"), _int(item, "unit")) for item in raw])
        dry_run = bool(request.data.get("dry_run"))

        def change(grid, alignment_set):
            plan = grid.align_groups(groups, apply=not dry_run)
            plan["dry_run"] = dry_run
            if dry_run:
                plan["first_row"] = plan.pop("row")  # a preview must not move the visible window
                return plan
            # The chapter the user picked first becomes the reading position, so "continue
            # reading" and the alignment agree on where they are. The window opens on it.
            entry = next((group for group in plan["groups"] if group["index"] == 0), None)
            if entry and alignment_set.work_id:
                # Position numbering is per edition; prefer the first column (the reference when
                # the grid reopens) if it is part of the group, else the group's first item.
                in_group = {version_id for version_id, _ in groups[0]}
                reference = next((c.version.id for c in grid.columns if c.version.id in in_group), groups[0][0][0])
                position = entry["positions"].get(reference)
                if position is not None:
                    ReadingProgress.objects.update_or_create(
                        user=request.user,
                        work_id=alignment_set.work_id,
                        defaults={"position": position, "character_index": None},
                    )
                    plan["reading_position"] = position
                plan["row"] = entry["row"]
            return plan

        return self._edit(request, pk, change)

    @action(detail=True, methods=["post"], url_path="reset")
    def reset(self, request, pk=None):
        """Discard every gap and join (and any rows left by the earlier anchor-based editor)."""

        def change(grid, alignment_set):
            reset_alignment(alignment_set)
            return None

        response = self._edit(request, pk, change)
        return response

    @action(detail=True, methods=["post"], url_path="auto-match-chapters")
    def auto_match_chapters(self, request, pk=None):
        """Align matching chapters onto shared rows by inserting gaps; nothing else moves."""

        def change(grid, alignment_set):
            if len(grid.columns) < 2:
                raise GridError("At least two editions are required to match chapters.")
            chapters_by_version = {
                column.version.id: list(
                    TextUnit.objects.filter(
                        version_id=column.version.text_version_id, kind=TextUnit.Kind.CHAPTER, parent__isnull=True
                    ).order_by("position", "id")
                )
                for column in grid.columns
            }
            matches = _label_matches(chapters_by_version)
            counts = {len(chapters) for chapters in chapters_by_version.values()}
            if not matches and len(counts) == 1:
                first_column = grid.columns[0].version.id
                matches = [
                    {version_id: chapters[index].id for version_id, chapters in chapters_by_version.items()}
                    for index in range(len(chapters_by_version[first_column]))
                ]
            aligned, gaps = grid.align_chapters(matches)
            return {"aligned_chapters": aligned, "inserted_gaps": gaps}

        return self._edit(request, pk, change)


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
            raise PermissionDenied("Only the alignment set owner can add editions.")
        serializer.save()

    def perform_update(self, serializer):
        target_set = serializer.validated_data.get("alignment_set", serializer.instance.alignment_set)
        if serializer.instance.alignment_set.owner_id != self.request.user.pk or target_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can edit its editions.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.alignment_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can delete its editions.")
        instance.delete()


class AlignmentGroupViewSet(viewsets.ModelViewSet):
    """Deprecated: rows of the earlier anchor-based editor. The grid no longer uses them."""

    serializer_class = AlignmentGroupSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"alignment_set": ["exact"], "sequence": ["exact", "gte", "lte"]}

    def get_queryset(self):
        return AlignmentGroup.objects.filter(
            alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("alignment_set")

    def perform_create(self, serializer):
        if serializer.validated_data["alignment_set"].owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can add groups.")
        serializer.save()

    def perform_update(self, serializer):
        target_set = serializer.validated_data.get("alignment_set", serializer.instance.alignment_set)
        if serializer.instance.alignment_set.owner_id != self.request.user.pk or target_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can edit its groups.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.alignment_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can delete its groups.")
        instance.delete()


class AlignmentMemberViewSet(viewsets.ModelViewSet):
    """Deprecated: cells of the earlier anchor-based editor. The grid no longer uses them."""

    serializer_class = AlignmentMemberSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"group": ["exact"], "alignment_version": ["exact"], "status": ["exact"]}

    def get_queryset(self):
        return AlignmentMember.objects.filter(
            group__alignment_set__in=visible_alignment_sets(self.request.user)
        ).select_related("group", "alignment_version", "start_unit", "end_unit")

    def perform_create(self, serializer):
        if serializer.validated_data["group"].alignment_set.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the alignment set owner can add members.")
        serializer.save()

    def perform_update(self, serializer):
        target_group = serializer.validated_data.get("group", serializer.instance.group)
        if (
            serializer.instance.group.alignment_set.owner_id != self.request.user.pk
            or target_group.alignment_set.owner_id != self.request.user.pk
        ):
            raise PermissionDenied("Only the alignment set owner can edit its members.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.group.alignment_set.owner_id != self.request.user.pk:
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
