"""Application services for recording checklist sightings."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tempus.models import Checklist, ChecklistItem, Observation
from tempus.services.geo import point_in_multipolygon


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
    date range, and, when set, a location inside the checklist's geo area.
    """
    observed_date = observed_at.date()
    items = (
        ChecklistItem.objects.filter(
            checklist__user_id=user.pk,
            species_id=species_id,
            checklist__auto_add=True,
        )
        .select_related("checklist", "checklist__geo_area")
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
        if candidate.geo_area_id:
            try:
                if not point_in_multipolygon(location, candidate.geo_area.geometry):
                    continue
            except (IndexError, KeyError, TypeError, ValueError):
                continue
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
    observations_linked = 0
    checklist_item_links_created = 0
    for observation in Observation.objects.filter(user=user).iterator():
        matches = matching_checklist_items(
            user=user,
            species_id=observation.species_id,
            observed_at=observation.observed_at,
            location=observation.location,
            checklist=checklist,
        )
        if not matches:
            continue

        existing_item_ids = set(
            observation.checklist_items.filter(
                pk__in=[item.pk for item in matches]
            ).values_list("pk", flat=True)
        )
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
def record_checklist_sighting(
    *,
    user: AbstractBaseUser,
    checklist_items: Iterable[ChecklistItem],
    observed_at: datetime,
    location: dict[str, Any] | None = None,
    count: int | None = None,
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
        notes=notes,
    )
    observation.checklist_items.set(items)
    link_observation_to_checklists(observation)
    return observation
