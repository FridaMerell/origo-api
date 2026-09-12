"""Application services for recording checklist sightings."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max, Prefetch

from tempus.models import Checklist, ChecklistItem, Locale, Observation, SpeciesCategory
from tempus.services.geo import point_in_multipolygon


def checklist_location_matches(*, checklist: Checklist, location: dict[str, Any]) -> bool:
    """Return whether ``location`` satisfies a checklist's optional areas.

    A locale and a GeoArea are alternative scopes. A checklist without either
    remains unrestricted by location.
    """
    areas = (checklist.locale, checklist.geo_area)
    if not any(areas):
        return True

    for area in areas:
        if area is None:
            continue
        try:
            if point_in_multipolygon(location, area.geometry):
                return True
        except (IndexError, KeyError, TypeError, ValueError):
            continue
    return False


def matching_checklist_items(
    *,
    user: AbstractBaseUser,
    species_id: Any,
    observed_at: datetime,
    location: dict[str, Any],
    checklist: Checklist | None = None,
) -> list[ChecklistItem]:
    """Checklist items on this user's checklists that the observation satisfies.

    Only checklist items with automatic adding enabled are considered. Matches
    require the same species, an observation date within the optional checklist
    date range, and, when set, a location inside the checklist's Locale or
    GeoArea.
    """
    observed_date = observed_at.date()
    items = (
        ChecklistItem.objects.filter(
            checklist__user_id=user.pk,
            species_id=species_id,
            checklist__auto_add=True,
        )
        .select_related("checklist", "checklist__geo_area", "checklist__locale")
    )
    if checklist is not None:
        items = items.filter(checklist=checklist)

    matches = []
    for item in items:
        candidate = item.checklist
        start = candidate.start_date
        end = candidate.end_date
        if start and observed_date < start:
            continue
        if end and observed_date > end:
            continue
        if checklist_location_matches(checklist=candidate, location=location):
            matches.append(item)
    return matches


def link_observation_to_checklists(observation: Observation) -> None:
    """Attach ``observation`` to every checklist item it satisfies."""
    items = matching_checklist_items(
        user=observation.user,
        species_id=observation.species_id,
        observed_at=observation.observed_at,
        location=observation.location,
    )
    if items:
        observation.checklist_items.add(*items)


def sync_observations_to_checklists(
    *, user: AbstractBaseUser, checklist: Checklist | None = None
) -> tuple[int, int]:
    """Link a user's existing observations to checklist items they satisfy.

    Returns ``(observations_linked, checklist_item_links_created)``. Existing
    links are retained and do not count towards either total.
    """
    items = ChecklistItem.objects.filter(
        checklist__user_id=user.pk,
        checklist__auto_add=True,
    ).select_related("checklist", "checklist__geo_area", "checklist__locale")
    if checklist is not None:
        items = items.filter(checklist=checklist)

    items_by_species = {}
    for item in items:
        items_by_species.setdefault(item.species_id, []).append(item)
    if not items_by_species:
        return 0, 0

    item_ids = [
        item.pk for species_items in items_by_species.values() for item in species_items
    ]
    observations = (
        Observation.objects.filter(user=user, species_id__in=items_by_species)
        .prefetch_related(
            Prefetch(
                "checklist_items",
                queryset=ChecklistItem.objects.filter(pk__in=item_ids),
                to_attr="_candidate_checklist_items",
            )
        )
        .iterator(chunk_size=500)
    )

    observations_linked = 0
    checklist_item_links_created = 0
    for observation in observations:
        observed_date = observation.observed_at.date()
        matches = []
        for item in items_by_species[observation.species_id]:
            candidate = item.checklist
            if candidate.start_date and observed_date < candidate.start_date:
                continue
            if candidate.end_date and observed_date > candidate.end_date:
                continue
            if not checklist_location_matches(
                checklist=candidate,
                location=observation.location,
            ):
                continue
            matches.append(item)
        if not matches:
            continue

        existing_item_ids = {
            item.pk for item in observation._candidate_checklist_items
        }
        missing_items = [
            item for item in matches if item.pk not in existing_item_ids
        ]
        if not missing_items:
            continue

        observation.checklist_items.add(*missing_items)
        observations_linked += 1
        checklist_item_links_created += len(missing_items)

    return observations_linked, checklist_item_links_created


@transaction.atomic
def add_category_species_to_checklist(
    *, checklist: Checklist, category: SpeciesCategory
) -> int:
    """Add any species in ``category``'s subtree that are missing from a checklist.

    Existing checklist items, including their notes and order, are retained.
    The category's direct and descendant species are appended in scientific-name
    order. Returns the number of new items.
    """
    existing_species_ids = set(
        checklist.items.values_list("species_id", flat=True)
    )
    category_species = category.effective_species_queryset().exclude(
        pk__in=existing_species_ids
    )
    next_sequence = (
        checklist.items.aggregate(max_sequence=Max("sequence"))["max_sequence"] or 0
    )
    new_items = [
        ChecklistItem(
            checklist=checklist,
            species=species,
            sequence=next_sequence + position,
            notes="",
        )
        for position, species in enumerate(category_species, start=1)
    ]
    if not new_items:
        return 0

    ChecklistItem.objects.bulk_create(new_items)
    sync_observations_to_checklists(user=checklist.user, checklist=checklist)
    return len(new_items)


@transaction.atomic
def record_checklist_sighting(
    *,
    user: AbstractBaseUser,
    checklist_items: Iterable[ChecklistItem],
    observed_at: datetime,
    location: dict[str, Any] | None = None,
    count: int | None = None,
    life_stage: str | None = None,
    locale: Locale | None = None,
    notes: str = "",
) -> Observation:
    """Create one observation and attach it to one or more checklist items."""
    items = tuple({item.pk: item for item in checklist_items}.values())
    if not items:
        raise ValidationError("At least one checklist item is required.")

    if any(item.checklist.user_id != user.pk for item in items):
        raise PermissionDenied("Every checklist must belong to this user.")

    species_id = items[0].species_id
    if any(item.species_id != species_id for item in items):
        raise ValidationError(
            "All checklist items must refer to the same species."
        )

    observation = Observation.objects.create(
        user=user,
        species=items[0].species,
        observed_at=observed_at,
        location=location or {},
        count=count,
        life_stage=life_stage,
        locale=locale,
        notes=notes,
    )
    observation.checklist_items.set(items)
    link_observation_to_checklists(observation)
    return observation
