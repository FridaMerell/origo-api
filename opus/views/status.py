from django.db.models import Count, Max, Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from opus.models import Annotation, Edition, ReadingProgress, TextUnit
from opus.access import visible_to_user


class ReadingStatusView(APIView):
    """Return every edition with a three-paragraph reading window."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        editions = visible_to_user(
            Edition.objects.select_related("work"), request.user, "work__"
        )
        work_id = request.query_params.get("work")
        if work_id:
            editions = editions.filter(work_id=work_id)
        editions = (
            editions
            .annotate(
                unit_count=Count("text_units", distinct=True),
                max_unit_position=Max("text_units__position"),
            )
            .prefetch_related(
                Prefetch(
                    "reading_progress",
                    queryset=ReadingProgress.objects.filter(user=request.user).select_related("unit"),
                    to_attr="request_reading_progress",
                ),
                Prefetch(
                    "text_units",
                    queryset=(
                        TextUnit.objects.order_by("position", "id")
                        .prefetch_related(
                            Prefetch(
                                "annotations",
                                queryset=(
                                    Annotation.objects.filter(user=request.user)
                                    .select_related("lexical_entry")
                                    .order_by("start_offset", "id")
                                ),
                                to_attr="request_annotations",
                            )
                        )
                    ),
                    to_attr="request_text_units",
                ),
            )
            .order_by("work__title", "title", "id")
        )
        rows = [self._row(edition) for edition in editions]
        return Response({"count": len(rows), "results": rows})

    @staticmethod
    def _row(edition):
        progress = edition.request_reading_progress[0] if edition.request_reading_progress else None
        if progress is None or not edition.max_unit_position:
            percent = 0
        else:
            percent = round((progress.unit.position / edition.max_unit_position) * 100)
            percent = max(0, min(100, percent))

        text_units = getattr(edition, "request_text_units", [])
        paragraphs = [
            unit
            for unit in text_units
            if unit.kind == TextUnit.Kind.PARAGRAPH
            and (not progress or unit.position >= progress.unit.position)
        ][:3]
        if not paragraphs:
            paragraphs = list(text_units[:3])

        return {
            "id": edition.id,
            "work_id": edition.work_id,
            "work_title": edition.work.title,
            "title": edition.title,
            "language": edition.language,
            "status": f"{percent}%",
            "status_percent": percent,
            "current_unit_id": progress.unit_id if progress else None,
            "updated_at": progress.updated_at if progress else None,
            "units": [
                {
                    "id": unit.id,
                    "kind": unit.kind,
                    "position": unit.position,
                    "label": unit.label,
                    "content": unit.content,
                    "annotations": [
                        {
                            "id": annotation.id,
                            "kind": annotation.kind,
                            "start_offset": annotation.start_offset,
                            "end_offset": annotation.end_offset,
                            "body": annotation.body,
                            "lexical_entry": (
                                {
                                    "id": annotation.lexical_entry.id,
                                    "lemma": annotation.lexical_entry.lemma,
                                    "language": annotation.lexical_entry.language,
                                    "part_of_speech": annotation.lexical_entry.part_of_speech,
                                    "gender": annotation.lexical_entry.gender,
                                    "inflection_data": annotation.lexical_entry.inflection_data,
                                }
                                if annotation.lexical_entry_id
                                else None
                            ),
                        }
                        for annotation in getattr(unit, "request_annotations", [])
                    ],
                }
                for unit in paragraphs
            ],
        }
