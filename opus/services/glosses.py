"""Finding known words in a text, so their definitions can be shown without an annotation per place."""

import re
from collections import namedtuple

from django.db.models.functions import Lower

from opus.models import LexicalForm

# Letters and digits, with hyphens and apostrophes inside the word; any other punctuation
# (typographic quotes, dashes, ellipses) ends it.
WORD = re.compile(r"\w+(?:['’\-]\w+)*")

# ``form`` is the matched ``LexicalForm``, or None when the word is the entry's lemma.
Gloss = namedtuple("Gloss", "start_offset end_offset entry form")


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

    for language, language_units in by_language.items():
        words = {unit.id: [(match.start(), match.end(), match.group().lower()) for match in WORD.finditer(unit.content)]
                 for unit in language_units}
        wanted = {word for unit_words in words.values() for _, _, word in unit_words}
        if not wanted:
            continue

        # The best match per word: the user's own entry before someone else's, a lemma before a form.
        best = {}

        def offer(word, entry, form):
            rank = (entry.owner_id != user.pk, form is not None, entry.id)
            if word not in best or rank < best[word][0]:
                best[word] = (rank, entry, form)

        in_language = entries.filter(language__iexact=language)
        for entry in in_language.annotate(word=Lower("lemma")).filter(word__in=wanted):
            offer(entry.word, entry, None)
        for form in (
            LexicalForm.objects.filter(entry__in=in_language.values("id"))
            .annotate(word=Lower("form"))
            .filter(word__in=wanted)
            .select_related("entry")
        ):
            offer(form.word, form.entry, form)
        if not best:
            continue

        for unit in language_units:
            annotated = [
                (annotation.start_offset, annotation.end_offset)
                for annotation in getattr(unit, "request_annotations", [])
                if annotation.start_offset is not None and annotation.end_offset is not None
            ]
            for start, end, word in words[unit.id]:
                if word not in best or any(start < taken_end and taken_start < end for taken_start, taken_end in annotated):
                    continue
                _, entry, form = best[word]
                unit.request_glosses.append(Gloss(start, end, entry, form))
