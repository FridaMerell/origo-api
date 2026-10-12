"""Finding known words in a text, so their definitions can be shown without an annotation per place."""

import re
from collections import namedtuple

from django.db.models import Prefetch
from django.db.models.functions import Lower

from opus.access import editable_lexical_entries
from opus.models import Glossary, LexicalEntry, LexicalForm

# Letters and digits, with hyphens and apostrophes inside the word; any other punctuation
# (typographic quotes, dashes, ellipses) ends it.
WORD = re.compile(r"\w+(?:['’\-]\w+)*")

# ``form`` is the matched ``LexicalForm``, or None when the word is the entry's lemma.
Gloss = namedtuple("Gloss", "start_offset end_offset entry form")


def entry_detail_prefetches(user, path=""):
    """What the reading view shows and edits for a word, for a queryset that reaches entries through ``path``.

    Its synonyms and forms, and ``request_glossaries``: the user's own glossaries that contain it.
    """

    return (
        f"{path}synonyms__target",
        f"{path}forms",
        Prefetch(
            f"{path}glossaries",
            queryset=Glossary.objects.filter(owner=user),
            to_attr="request_glossaries",
        ),
    )


def attach_entry_permissions(units, user):
    """Set ``request_can_edit`` on every entry the units show: whether ``user`` may change it.

    Covers the entries of the units' annotations (``request_annotations``) and of their glosses
    (``request_glosses``), with one query for all of them.
    """

    entries = [
        annotation.lexical_entry
        for unit in units
        for annotation in getattr(unit, "request_annotations", [])
        if annotation.lexical_entry_id
    ] + [gloss.entry for unit in units for gloss in getattr(unit, "request_glosses", [])]
    editable = set(
        editable_lexical_entries(LexicalEntry.objects.filter(pk__in={entry.pk for entry in entries}), user)
        .values_list("pk", flat=True)
    ) if entries else set()
    for entry in entries:
        entry.request_can_edit = entry.pk in editable


def attach_glosses(units, entries, user):
    """Set ``request_glosses`` on each unit: its words that are a lemma or a form of one of ``entries``.

    A word is only looked up among entries in the language of the unit's edition, so ``unit.version``
    must be loaded. Places the user has annotated (``request_annotations``) are left to the annotation.
    Only the words that occur in ``units`` are looked up, never the whole lexicon.
    """

    by_language = {}
    for unit in units:
        unit.request_glosses = []
        by_language.setdefault(unit.version.language.strip().lower(), []).append(unit)

    # Per unit, its words that are free to gloss: (start, end, lowercased word).
    words = {}
    # Per language and word, the best match as (rank, entry id, form id): the user's own entry
    # before someone else's, a lemma before a form. Only ids are read for the candidates, since a
    # common word can be in many users' lists.
    best = {}
    for language, language_units in by_language.items():
        for unit in language_units:
            annotated = [
                (annotation.start_offset, annotation.end_offset)
                for annotation in getattr(unit, "request_annotations", [])
                if annotation.start_offset is not None and annotation.end_offset is not None
            ]
            words[unit.id] = [
                (match.start(), match.end(), match.group().lower())
                for match in WORD.finditer(unit.content)
                if not any(match.start() < taken_end and taken_start < match.end() for taken_start, taken_end in annotated)
            ]
        wanted = {word for unit in language_units for _, _, word in words[unit.id]}
        if not wanted:
            continue

        in_language = entries.filter(language__iexact=language)
        candidates = [
            (word, entry_id, owner_id, None)
            for word, entry_id, owner_id in in_language.annotate(word=Lower("lemma"))
            .filter(word__in=wanted)
            .order_by()
            .values_list("word", "id", "owner_id")
        ] + list(
            LexicalForm.objects.filter(entry__in=in_language.values("id"))
            .annotate(word=Lower("form"))
            .filter(word__in=wanted)
            .order_by()
            .values_list("word", "entry_id", "entry__owner_id", "id")
        )
        for word, entry_id, owner_id, form_id in candidates:
            rank = (owner_id != user.pk, form_id is not None, entry_id)
            if (language, word) not in best or rank < best[language, word][0]:
                best[language, word] = (rank, entry_id, form_id)
    if not best:
        return

    # The details are loaded once, and only for the entries that are shown.
    chosen = LexicalEntry.objects.prefetch_related(*entry_detail_prefetches(user)).in_bulk(
        {entry_id for _, entry_id, _ in best.values()}
    )
    for language, language_units in by_language.items():
        for unit in language_units:
            for start, end, word in words[unit.id]:
                if (language, word) not in best:
                    continue
                _, entry_id, form_id = best[language, word]
                entry = chosen.get(entry_id)
                # Removed by someone else between the two queries.
                if entry is None:
                    continue
                form = next((form for form in entry.forms.all() if form.id == form_id), None)
                unit.request_glosses.append(Gloss(start, end, entry, form))
