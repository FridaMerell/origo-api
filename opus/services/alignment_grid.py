"""Parallel-reading grid, derived from the paragraphs plus a few stored edits.

Every edition is a column. Its cells are its paragraphs in ``(position, id)`` order, changed
only by two kinds of stored edits:

* ``AlignmentGap`` — ``count`` empty cells directly above one paragraph;
* ``AlignmentSpan`` — one cell covering the paragraphs from ``start_unit`` to ``end_unit``.

Rows are the cell indexes, so row ``r`` of every column sits side by side. Nothing else is
stored: a book of thousands of paragraphs costs a handful of rows, and every edit below
writes at most a couple of them, regardless of where in the book it happens.
"""

from bisect import bisect_left

from django.db import transaction
from django.db.models import F, Q

from opus.models import AlignmentGap, AlignmentSpan, AlignmentVersion, TextUnit

GAP = "gap"
TEXT = "text"


class GridError(ValueError):
    """The requested edit does not apply to the current grid."""


class Column:
    """One edition: its paragraph ids and the stored edits that shape its cells."""

    def __init__(self, version, gaps, spans):
        self.version = version
        rows = list(
            TextUnit.objects.filter(version_id=version.text_version_id, kind=TextUnit.Kind.PARAGRAPH)
            .order_by("position", "id")
            .values_list("id", "position", "parent_id")
        )
        self.paragraph_ids = [unit_id for unit_id, _, _ in rows]
        self.paragraph_positions = [position for _, position, _ in rows]
        self.paragraph_chapters = [chapter_id for _, _, chapter_id in rows]
        self.index_of = {unit_id: index for index, unit_id in enumerate(self.paragraph_ids)}
        self.gaps = {}
        for gap in gaps:
            index = self.index_of.get(gap.before_unit_id)
            if index is not None:
                self.gaps[index] = gap.count
        self.spans = {}
        for span in spans:
            start, end = self.index_of.get(span.start_unit_id), self.index_of.get(span.end_unit_id)
            if start is not None and end is not None and end > start:
                self.spans[start] = end
        self.cells = self._cells()
        # Per paragraph index: ``(first paragraph index of its cell, row)`` - a joined cell's
        # paragraphs share one row. ``None`` would mean a paragraph without a cell (cannot happen).
        self.cell_of = [None] * len(self.paragraph_ids)
        for row, cell in enumerate(self.cells):
            if cell[0] == TEXT:
                for index in range(cell[1], cell[2] + 1):
                    self.cell_of[index] = (cell[1], row)

    def next_chapter(self, index):
        """Index of the first paragraph after ``index`` that belongs to another chapter, or ``None``."""

        chapter = self.paragraph_chapters[index]
        return next(
            (later for later in range(index + 1, len(self.paragraph_ids)) if self.paragraph_chapters[later] != chapter),
            None,
        )

    def _cells(self):
        """``(GAP, anchor_index)`` or ``(TEXT, first_index, last_index)`` per row."""

        cells = []
        index, total = 0, len(self.paragraph_ids)
        while index < total:
            cells.extend([(GAP, index)] * self.gaps.get(index, 0))
            last = self.spans.get(index, index)
            cells.append((TEXT, index, last))
            index = last + 1
        return cells

    def cell(self, row):
        if not 0 <= row < len(self.cells):
            raise GridError("The row does not exist in this edition.")
        return self.cells[row]

    def unit_ids(self, cell):
        return self.paragraph_ids[cell[1] : cell[2] + 1] if cell[0] == TEXT else []


class Grid:
    """All columns of one alignment set."""

    def __init__(self, alignment_set):
        self.alignment_set = alignment_set
        versions = list(AlignmentVersion.objects.filter(alignment_set=alignment_set).order_by("display_order", "id"))
        gaps = list(AlignmentGap.objects.filter(alignment_version__alignment_set=alignment_set))
        spans = list(AlignmentSpan.objects.filter(alignment_version__alignment_set=alignment_set))
        self.columns = [
            Column(
                version,
                [gap for gap in gaps if gap.alignment_version_id == version.id],
                [span for span in spans if span.alignment_version_id == version.id],
            )
            for version in versions
        ]

    @property
    def total_rows(self):
        return max((len(column.cells) for column in self.columns), default=0)

    def pages(self, size):
        """The reader's pages as ``(first_row, end_row)``, like a book's.

        Every chapter of the first edition (the reference column, as for reading positions)
        starts on a new page; a longer chapter continues over pages of at most ``size`` rows.
        """

        total = self.total_rows
        if total == 0:
            return []
        starts = {0}
        if self.columns:
            column = self.columns[0]
            for row, cell in enumerate(column.cells):
                if cell[0] != TEXT:
                    continue
                index = cell[1]
                # The edition's first paragraph opens its first chapter too, even when other
                # editions' text (e.g. a foreword) fills the rows above it.
                if index == 0 or column.paragraph_chapters[index] != column.paragraph_chapters[index - 1]:
                    starts.add(row)
        boundaries = sorted(starts) + [total]
        pages = []
        for first, end in zip(boundaries, boundaries[1:]):
            pages.extend((row, min(row + size, end)) for row in range(first, end, size))
        return pages

    def row_at_position(self, position):
        """Row of the first paragraph at or after ``position`` in the first edition (or ``None``).

        A reading position is a paragraph position and only means something within one
        edition's numbering, so the first column (``display_order``) is the reference.
        """

        if not self.columns:
            return None
        column = self.columns[0]
        index = bisect_left(column.paragraph_positions, position)
        if index >= len(column.paragraph_ids):
            return None
        return next(
            (row for row, cell in enumerate(column.cells) if cell[0] == TEXT and cell[1] <= index <= cell[2]), None
        )

    def row_for_unit(self, version_id, unit_id):
        """Row of a paragraph, or a chapter's first paragraph, in one edition's column.

        ``None`` if the unit doesn't resolve to a paragraph cell (e.g. an empty chapter).
        """

        try:
            return self._resolve_group([(version_id, unit_id)])[0][2]
        except GridError:
            return None

    def column(self, version_id):
        for column in self.columns:
            if column.version.id == version_id:
                return column
        raise GridError("The edition is not part of this alignment set.")

    # -- edits (each writes O(1) rows) ------------------------------------------------------

    def insert_gap(self, version_id, row):
        """Push the cell at ``row`` and everything below it one row down in one edition."""

        column = self.column(version_id)
        self._add_gaps(column, column.cell(row)[1], 1)

    def remove_gap(self, version_id, row):
        """Remove the gap at ``row``; everything below moves one row up."""

        column = self.column(version_id)
        cell = column.cell(row)
        if cell[0] != GAP:
            raise GridError("The cell is not a gap.")
        gap = AlignmentGap.objects.get(alignment_version=column.version, before_unit_id=column.paragraph_ids[cell[1]])
        if gap.count <= 1:
            gap.delete()
        else:
            AlignmentGap.objects.filter(pk=gap.pk).update(count=F("count") - 1)

    def join_next(self, version_id, row):
        """Join the cell at ``row`` with the one below it (both must hold text)."""

        column = self.column(version_id)
        first = column.cell(row)
        if row + 1 >= len(column.cells):
            raise GridError("There is no cell below to join with.")
        second = column.cell(row + 1)
        if first[0] != TEXT or second[0] != TEXT:
            raise GridError("Both cells must contain text to be joined.")
        with transaction.atomic():
            AlignmentSpan.objects.filter(
                alignment_version=column.version,
                start_unit_id__in=[column.paragraph_ids[first[1]], column.paragraph_ids[second[1]]],
            ).delete()
            AlignmentSpan.objects.create(
                alignment_version=column.version,
                start_unit_id=column.paragraph_ids[first[1]],
                end_unit_id=column.paragraph_ids[second[2]],
            )

    def split_last(self, version_id, row):
        """Split the last paragraph off a joined cell; it becomes its own cell below."""

        column = self.column(version_id)
        cell = column.cell(row)
        if cell[0] != TEXT or cell[2] <= cell[1]:
            raise GridError("The cell holds a single paragraph.")
        span = AlignmentSpan.objects.get(alignment_version=column.version, start_unit_id=column.paragraph_ids[cell[1]])
        if cell[2] - 1 <= cell[1]:
            span.delete()
        else:
            span.end_unit_id = column.paragraph_ids[cell[2] - 1]
            span.save(update_fields=["end_unit"])

    def align_chapters(self, matches):
        """Add gaps so the first paragraph of each matched chapter shares a row.

        ``matches`` is a list of ``{version_id: chapter_unit_id}``. Returns
        ``(aligned_chapters, inserted_gaps)``. A chapter is skipped when its first paragraph
        is missing or sits inside a joined cell.
        """

        first = {}
        for column in self.columns:
            chapter_ids = {match[column.version.id] for match in matches if column.version.id in match}
            first[column.version.id] = {}
            for parent_id, unit_id in (
                TextUnit.objects.filter(
                    version_id=column.version.text_version_id, kind=TextUnit.Kind.PARAGRAPH, parent_id__in=chapter_ids
                )
                .order_by("position", "id")
                .values_list("parent_id", "id")
            ):
                first[column.version.id].setdefault(parent_id, column.index_of[unit_id])
        resolved = []
        for number, match in enumerate(matches):
            targets = []
            for version_id, chapter_id in match.items():
                column = self.column(version_id)
                index = first[version_id].get(chapter_id)
                cell = column.cell_of[index] if index is not None else None
                # Skipped: a chapter without text, or one whose first paragraph is inside a joined cell.
                if cell is not None and cell[0] == index:
                    targets.append((column, index, cell[1]))
            if len(targets) >= 2:
                resolved.append((number, targets))
        resolved.sort(key=lambda entry: min(row for _, _, row in entry[1]))
        added, plan = self._plan(resolved, strict=False)
        with transaction.atomic():
            for (version_id, index), count in added.items():
                self._add_gaps(self.column(version_id), index, count)
        return len(plan), sum(added.values())

    def _resolve_group(self, items):
        """Resolve ``(version_id, unit_id)`` items to ``(column, first paragraph index, row)``.

        A unit may be a paragraph or a chapter (whose first paragraph is used).
        """

        targets = []
        for version_id, unit_id in items:
            column = self.column(version_id)
            unit = TextUnit.objects.filter(pk=unit_id, version_id=column.version.text_version_id).first()
            if unit is None:
                raise GridError("The text does not belong to that edition.")
            if unit.kind == TextUnit.Kind.CHAPTER:
                unit = (
                    TextUnit.objects.filter(parent=unit, kind=TextUnit.Kind.PARAGRAPH).order_by("position", "id").first()
                )
                if unit is None:
                    raise GridError("The chapter has no paragraphs.")
            index = column.index_of.get(unit.id)
            if index is None:
                raise GridError("Only paragraphs and chapters can be aligned.")
            row = next(
                (number for number, cell in enumerate(column.cells) if cell[0] == TEXT and cell[1] <= index <= cell[2]),
                None,
            )
            if row is None:
                raise GridError("The paragraph is not a cell of its own.")
            targets.append((column, column.cells[row][1], row))
        if len({column.version.id for column, _, _ in targets}) != len(targets):
            raise GridError("Pick one text per edition.")
        return targets

    def align_groups(self, groups, apply=True):
        """Give the cells of each group the same row by adding gaps above the higher ones.

        ``groups`` is a list of groups, each a list of ``(version_id, unit_id)``. Nothing moves
        up: the lower-lying cells stay put and the others are pushed down to meet them, group by
        group from the top of the book down. With ``apply=False`` nothing is written and the
        returned plan is only what *would* happen.

        Returns ``{"groups": [{"index", "row", "gaps": {version_id: count}}], "inserted_gaps", "row"}``
        where ``index`` is the group's position in ``groups``, ``row`` is its final row (0-based)
        and the top-level ``row`` is that of the first group from the top of the book.
        """

        resolved = [(number, self._resolve_group(items)) for number, items in enumerate(groups)]
        resolved.sort(key=lambda entry: min(row for _, _, row in entry[1]))
        added, plan = self._plan(resolved, strict=True)
        if apply and added:
            with transaction.atomic():
                for (version_id, index), count in added.items():
                    self._add_gaps(self.column(version_id), index, count)
        return {
            "groups": plan,
            "inserted_gaps": sum(added.values()),
            "row": plan[0]["row"] if plan else 0,
        }

    # -- helpers ----------------------------------------------------------------------------

    def _plan(self, resolved, strict):
        """Gaps that give each group's cells one row, while leaving the rest of the book as it was.

        ``resolved`` is ``[(number, [(column, first paragraph index, row)])]``, top of the book
        first. A group is aligned by pushing the higher cells down to the lowest one; that push
        would also move everything after it in those editions, undoing alignments further down.
        So the push is evened out where the group's chapter ends: each other edition in the group
        gets the missing gaps where *its* next chapter starts, and an edition outside the group
        gets them at the corresponding row. From there on every edition has moved by the same
        amount, so only the synced chapter itself changes.

        Returns ``(added, plan)``: ``{(version_id, paragraph index): gap count}`` and one
        ``{"index", "row", "gaps", "positions"}`` per aligned group. With ``strict`` a group out
        of book order raises ``GridError``; otherwise it is skipped.
        """

        inserts = {column.version.id: [] for column in self.columns}  # (paragraph index, count)
        last_index = {column.version.id: -1 for column in self.columns}
        plan = []

        def shift(version_id, index):
            return sum(count for at, count in inserts[version_id] if at <= index)

        def insert(column, index, count):
            # Gaps go above a whole cell, never inside a joined one.
            inserts[column.version.id].append((column.cell_of[index][0], count))

        def first_at_or_below(column, row):
            """Index of the first paragraph whose (shifted) row is at or below ``row``."""
            running, pending = 0, sorted(inserts[column.version.id])
            for index, cell in enumerate(column.cell_of):
                while pending and pending[0][0] <= index:
                    running += pending.pop(0)[1]
                if cell is not None and cell[1] + running >= row:
                    return index
            return None

        for position, (number, targets) in enumerate(resolved):
            if any(index <= last_index[column.version.id] for column, index, _ in targets):
                if strict:
                    raise GridError("Chapters must be added in the order they appear in the book, once each.")
                continue
            # What later groups of this same sync will align anyway: evening out there is redundant
            # (and would only add blank rows), since that group sets the rows itself.
            later = resolved[position + 1 :]
            aligned_later = {(column.version.id, index) for _, items in later for column, index, _ in items}
            editions_later = {version_id for version_id, _ in aligned_later}
            current = {column.version.id: row + shift(column.version.id, index) for column, index, row in targets}
            target = max(current.values())
            missing = {version_id: target - row for version_id, row in current.items()}
            most = max(missing.values())

            # Where an edition that already sits on the target row reaches its next chapter: the
            # row from which every edition must have moved by ``most``.
            anchor = None
            for column, index, _ in targets:
                following = column.next_chapter(index)
                if missing[column.version.id] == 0 and following is not None:
                    row = column.cell_of[following][1] + shift(column.version.id, following)
                    anchor = row if anchor is None else min(anchor, row)

            gaps = {}
            for column, index, _ in targets:
                version_id = column.version.id
                if missing[version_id]:
                    insert(column, index, missing[version_id])
                    gaps[version_id] = missing[version_id]
            if most:
                for column, index, _ in targets:
                    extra = most - missing[column.version.id]
                    following = column.next_chapter(index)
                    if extra and following is not None and (column.version.id, following) not in aligned_later:
                        insert(column, following, extra)
                        gaps[column.version.id] = gaps.get(column.version.id, 0) + extra
                if anchor is not None:
                    in_group = {column.version.id for column, _, _ in targets}
                    for column in self.columns:
                        if column.version.id in in_group or column.version.id in editions_later:
                            continue
                        at = first_at_or_below(column, anchor)
                        if at is not None:
                            insert(column, at, most)
                            gaps[column.version.id] = most

            for column, index, _ in targets:
                last_index[column.version.id] = index
            plan.append(
                {
                    "index": number,
                    "row": target,
                    "gaps": gaps,
                    "positions": {column.version.id: column.paragraph_positions[index] for column, index, _ in targets},
                }
            )

        added = {}
        for version_id, items in inserts.items():
            for at, count in items:
                added[(version_id, at)] = added.get((version_id, at), 0) + count
        return added, plan

    @staticmethod
    def _add_gaps(column, index, count):
        unit_id = column.paragraph_ids[index]
        gap, created = AlignmentGap.objects.get_or_create(
            alignment_version=column.version, before_unit_id=unit_id, defaults={"count": count}
        )
        if not created:
            AlignmentGap.objects.filter(pk=gap.pk).update(count=F("count") + count)


def release_unit(unit):
    """Detach a paragraph from gaps and spans before it is deleted.

    Gaps above it move to the next paragraph of the edition (or vanish at the end); a span that
    starts or ends on it shrinks by that paragraph, and disappears once a single one is left.
    Call inside the deleting transaction.
    """

    if unit.kind != TextUnit.Kind.PARAGRAPH:
        return
    siblings = TextUnit.objects.filter(version_id=unit.version_id, kind=TextUnit.Kind.PARAGRAPH).exclude(pk=unit.pk)
    after = (
        siblings.filter(Q(position__gt=unit.position) | Q(position=unit.position, id__gt=unit.id))
        .order_by("position", "id")
        .first()
    )
    before = (
        siblings.filter(Q(position__lt=unit.position) | Q(position=unit.position, id__lt=unit.id))
        .order_by("-position", "-id")
        .first()
    )

    for gap in AlignmentGap.objects.filter(before_unit=unit):
        if after is not None:
            other, created = AlignmentGap.objects.get_or_create(
                alignment_version_id=gap.alignment_version_id, before_unit=after, defaults={"count": gap.count}
            )
            if not created:
                AlignmentGap.objects.filter(pk=other.pk).update(count=F("count") + gap.count)
        gap.delete()

    for span in AlignmentSpan.objects.filter(start_unit=unit):
        if after is None or span.end_unit_id == after.id or span.end_unit_id == unit.id:
            span.delete()
        else:
            AlignmentSpan.objects.filter(pk=span.pk).update(start_unit=after)
    for span in AlignmentSpan.objects.filter(end_unit=unit).exclude(start_unit=unit):
        if before is None or span.start_unit_id == before.id:
            span.delete()
        else:
            AlignmentSpan.objects.filter(pk=span.pk).update(end_unit=before)


def reset(alignment_set):
    """Discard every edit (and the rows of the earlier anchor-based editor)."""

    AlignmentGap.objects.filter(alignment_version__alignment_set=alignment_set).delete()
    AlignmentSpan.objects.filter(alignment_version__alignment_set=alignment_set).delete()
    alignment_set.groups.all().delete()
