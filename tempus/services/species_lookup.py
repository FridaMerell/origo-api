"""Match free-text species values from an imported list against ``Species``.

A value is a Swedish name, a scientific name or a Dyntaxa taxon id. Names are
compared without regard to case, spaces or hyphens.
"""

import re

from django.db.models import Q, Value
from django.db.models.functions import Lower, Replace

from tempus.models import Species

# More digits than this cannot be a taxon id and would overflow the column.
_MAX_TAXON_ID_DIGITS = 18


def _value_key(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def _name_key(field: str):
    """The database side of :func:`_value_key` for one name column."""
    return Replace(
        Replace(Lower(field), Value(" "), Value("_")), Value("-"), Value("_")
    )


def match_species(values) -> tuple[list, list[str]]:
    """Return ``(species ids, the values no species answered to)``."""
    by_key = {_value_key(value): value.strip() for value in values if value.strip()}
    taxon_ids = [
        int(key)
        for key in by_key
        if key.isdecimal() and len(key) <= _MAX_TAXON_ID_DIGITS
    ]
    matches = (
        Species.objects.annotate(
            swedish_key=_name_key("swedish_name"),
            scientific_key=_name_key("scientific_name"),
        )
        .filter(
            Q(swedish_key__in=by_key)
            | Q(scientific_key__in=by_key)
            | Q(dyntaxa_taxon_id__in=taxon_ids)
        )
        .values_list("id", "swedish_key", "scientific_key", "dyntaxa_taxon_id")
    )

    species_ids = []
    answered = set()
    for species_id, swedish_key, scientific_key, taxon_id in matches:
        species_ids.append(species_id)
        answered.update((swedish_key, scientific_key, str(taxon_id)))
    unmatched = [value for key, value in by_key.items() if key not in answered]
    return species_ids, unmatched
