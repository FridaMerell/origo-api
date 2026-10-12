from django.db.models import Count, Max, Prefetch
from django.http import Http404
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from opus.models import Annotation, Edition, LexicalForm, ReadingProgress, TextUnit, Work
from opus.access import visible_to_user
from opus.serializers import ReadingProgressSerializer
from opus.serializers.lexicon import synonym_payload
from opus.services.glosses import attach_entry_permissions, entry_detail_prefetches


def get_visible_work_or_404(user, work_id):
    try:
        return visible_to_user(Work.objects.all(), user).get(pk=work_id)
    except Work.DoesNotExist as exc:
        raise Http404 from exc


def lexical_form_payload(form):
    return {
        "id": form.id,
        "form": form.form,
        "kind": form.kind,
        "inflection": form.inflection,
        **{name: getattr(form, name) for name in LexicalForm.GRAMMAR_FIELDS},
        "is_uncertain": form.is_uncertain,
    }


def lexical_entry_payload(entry):
    """A word as the reading view shows and edits it, without a request per word.

    The entry must be loaded with ``opus.services.glosses.entry_detail_prefetches``: ``glossaries``
    is read from ``request_glossaries``, and the reader saves it back, so it must never be guessed.
    ``can_edit`` is ``request_can_edit`` from ``attach_entry_permissions``.
    """

    return {
        "id": entry.id,
        "lemma": entry.lemma,
        "language": entry.language,
        "part_of_speech": entry.part_of_speech,
        "gender": entry.gender,
        "inflection_data": entry.inflection_data,
        "translation": entry.translation,
        "definition": entry.definition,
        "connotations": entry.connotations,
        "connotation_note": entry.connotation_note,
        "synonyms": synonym_payload(entry),
        "glossaries": [glossary.id for glossary in entry.request_glossaries],
        "forms": [lexical_form_payload(form) for form in entry.forms.all()],
        "can_edit": entry.request_can_edit,
        "owner": entry.owner_id,
    }


def reading_unit_payload(unit):
    """One reading unit with the requesting user's annotations (``request_annotations``).

    ``glosses`` are the known words found in the text (``request_glosses``, see
    ``opus.services.glosses``); empty where they have not been looked up.
    ``unit.parent`` must be loaded (``select_related("parent")``).
    """

    return {
        "id": unit.id,
        "kind": unit.kind,
        "position": unit.position,
        "label": unit.label,
        "content": unit.content,
        "chapter": (
            {
                "id": unit.parent_id,
                "position": unit.parent.position,
                "label": unit.parent.label,
            }
            if unit.parent_id and unit.parent.kind == TextUnit.Kind.CHAPTER
            else None
        ),
        "annotations": [
            {
                "id": annotation.id,
                "kind": annotation.kind,
                "target_kind": annotation.target_kind,
                "start_offset": annotation.start_offset,
                "end_offset": annotation.end_offset,
                "body": annotation.body,
                "lexical_entry": (
                    lexical_entry_payload(annotation.lexical_entry) if annotation.lexical_entry_id else None
                ),
            }
            for annotation in getattr(unit, "request_annotations", [])
        ],
        "glosses": [
            {
                "start_offset": gloss.start_offset,
                "end_offset": gloss.end_offset,
                "lexical_entry": lexical_entry_payload(gloss.entry),
                "form": lexical_form_payload(gloss.form) if gloss.form else None,
            }
            for gloss in getattr(unit, "request_glosses", [])
        ],
    }


class ReadingView(APIView):
    """Return one work's editions with a shared three-paragraph reading window."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, work_id):
        work = get_visible_work_or_404(request.user, work_id)

        progress = ReadingProgress.objects.filter(user=request.user, work=work).first()
        paragraph_queryset = TextUnit.objects.filter(kind=TextUnit.Kind.PARAGRAPH).select_related("parent")
        if progress is not None:
            paragraph_queryset = paragraph_queryset.filter(position__gte=progress.position)
        paragraph_queryset = paragraph_queryset.order_by("position", "id")[:3]
        editions = (
            Edition.objects.filter(work=work)
            .annotate(
                unit_count=Count("text_units", distinct=True),
                max_unit_position=Max("text_units__position"),
            )
            .prefetch_related(
                Prefetch(
                    "text_units",
                    queryset=(
                        paragraph_queryset.prefetch_related(
                            Prefetch(
                                "annotations",
                                queryset=(
                                    Annotation.objects.filter(user=request.user)
                                    .select_related("lexical_entry")
                                    .prefetch_related(*entry_detail_prefetches(request.user, "lexical_entry__"))
                                    .order_by("start_offset", "id")
                                ),
                                to_attr="request_annotations",
                            )
                        )
                    ),
                    to_attr="request_paragraphs",
                ),
                Prefetch(
                    "text_units",
                    queryset=TextUnit.objects.filter(
                        kind=TextUnit.Kind.CHAPTER, parent__isnull=True
                    ).order_by("position", "id"),
                    to_attr="request_chapters",
                ),
            )
            .order_by("title", "id")
        )
        editions = list(editions)
        attach_entry_permissions(
            [unit for edition in editions for unit in edition.request_paragraphs], request.user
        )
        return Response(
            {
                "work": {"id": work.id, "title": work.title},
                "position": progress.position if progress else 0,
                "character_index": progress.character_index if progress else None,
                "updated_at": progress.updated_at if progress else None,
                "editions": [self._row(edition, progress) for edition in editions],
            }
        )

    @staticmethod
    def _row(edition, progress):
        if progress is None or not edition.max_unit_position:
            percent = 0
        else:
            percent = round((progress.position / edition.max_unit_position) * 100)
            percent = max(0, min(100, percent))

        paragraphs = getattr(edition, "request_paragraphs", [])
        chapters = getattr(edition, "request_chapters", [])

        return {
            "id": edition.id,
            "title": edition.title,
            "language": edition.language,
            "status": f"{percent}%",
            "status_percent": percent,
            "chapters": [
                {
                    "id": unit.id,
                    "position": unit.position,
                    "label": unit.label,
                }
                for unit in chapters
            ],
            "units": [reading_unit_payload(unit) for unit in paragraphs],
        }


class WorkReadingProgressView(APIView):
    """Replace the current user's reading position for one work."""

    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, work_id):
        work = get_visible_work_or_404(request.user, work_id)
        if "position" not in request.data:
            raise ValidationError({"position": ["This field is required."]})

        payload = request.data.copy()
        payload["work"] = work.pk
        serializer = ReadingProgressSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        progress, _ = ReadingProgress.objects.update_or_create(
            user=request.user,
            work=work,
            defaults={
                "position": serializer.validated_data["position"],
                "character_index": serializer.validated_data.get("character_index"),
            },
        )
        return Response(ReadingProgressSerializer(progress, context={"request": request}).data)
