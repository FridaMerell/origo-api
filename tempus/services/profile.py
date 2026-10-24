"""One user's Tempus over all time: totals, species, years, months, places,
followed species, planning and BirdNET.

Everything is aggregated in the database; only one row per observed species
leaves it, to pick the most observed, newest and rarest species and to count
each year's new species. Years and months follow Swedish local time, as in
the year summary.
"""

from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Count, Exists, FloatField, Func, IntegerField, Min, OuterRef, Q, Sum
from django.db.models.fields.json import KT
from django.db.models.functions import Cast, ExtractMonth, ExtractYear

from tempus.models import (
    BirdnetDetection,
    BirdnetDevice,
    Checklist,
    ChecklistItem,
    Locale,
    Observation,
    Route,
    SpeciesFollow,
)
from tempus.services.geo import haversine_m
from tempus.services.route_planner import _redlist_code
from tempus.services.year_summary import STOCKHOLM, _first_observation, _rarity

TOP_LOCALE_LIMIT = 5


def profile_summary(*, user: AbstractBaseUser) -> dict:
    observations = Observation.objects.filter(user=user).order_by()

    totals = observations.aggregate(
        observation_count=Count("pk"),
        species_count=Count("species", distinct=True),
        locale_count=Count("locale", distinct=True),
        photo_count=Sum(Func("photos", function="CARDINALITY", output_field=IntegerField())),
    )
    summary = {
        "username": user.get_username(),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "date_joined": user.date_joined,
        **totals,
        "photo_count": totals["photo_count"] or 0,
        "own_locale_count": Locale.objects.filter(user=user).count(),
        "follows": _follows(user),
        "planning": _planning(user),
        "birdnet": _birdnet(user),
    }
    if not totals["observation_count"]:
        summary["years"] = []
        return summary

    species = _species(observations)
    rated = [row for row in species if row["significance"] is not None]
    summary.update(
        first_observation=_first_observation(observations),
        red_listed_count=sum(bool(row["red_list_category"]) for row in species),
        most_observed=max(species, key=lambda row: (row["observation_count"], row["first_observed_at"])),
        newest=max(species, key=lambda row: row["first_observed_at"]),
        rarest=max(rated, key=_rarity) if rated else None,
        groups=_groups(observations),
        years=_years(observations, species),
        months=_months(observations),
        top_locales=_top_locales(observations),
        extremes=_extremes(observations),
    )
    return summary


def _species(observations) -> list[dict]:
    """One row per species the user has observed."""
    rows = observations.values(
        "species_id",
        "species__dyntaxa_taxon_id",
        "species__swedish_name",
        "species__scientific_name",
        "species__significance",
        "species__api_data__redlistCategory",
    ).annotate(observation_count=Count("pk"), first_observed_at=Min("observed_at"))
    return [
        {
            "id": str(row["species_id"]),
            "dyntaxa_taxon_id": row["species__dyntaxa_taxon_id"],
            "swedish_name": row["species__swedish_name"],
            "scientific_name": row["species__scientific_name"],
            "significance": row["species__significance"],
            "red_list_category": _redlist_code(row["species__api_data__redlistCategory"]),
            "observation_count": row["observation_count"],
            "first_observed_at": row["first_observed_at"],
        }
        for row in rows
    ]


def _groups(observations) -> list[dict]:
    """Observed species per primary category, the largest group first."""
    rows = (
        observations.filter(species__category_memberships__category__is_primary=True)
        .values(
            "species__category_memberships__category_id",
            "species__category_memberships__category__label",
            "species__category_memberships__category__taxon_id",
        )
        .annotate(species_count=Count("species", distinct=True))
        .order_by("-species_count", "species__category_memberships__category__label")
    )
    return [
        {
            "id": str(row["species__category_memberships__category_id"]),
            "label": row["species__category_memberships__category__label"],
            "taxon_id": row["species__category_memberships__category__taxon_id"],
            "species_count": row["species_count"],
        }
        for row in rows
    ]


def _years(observations, species: list[dict]) -> list[dict]:
    """Every year with observations, newest first; a species is new in the
    year the user first observed it."""
    new_by_year: dict[int, int] = {}
    for row in species:
        year = row["first_observed_at"].astimezone(STOCKHOLM).year
        new_by_year[year] = new_by_year.get(year, 0) + 1
    rows = (
        observations.annotate(year=ExtractYear("observed_at", tzinfo=STOCKHOLM))
        .values("year")
        .annotate(observation_count=Count("pk"), species_count=Count("species", distinct=True))
        .order_by("-year")
    )
    return [{**row, "new_species_count": new_by_year.get(row["year"], 0)} for row in rows]


def _months(observations) -> list[int]:
    """Observations per calendar month, all years together."""
    months = [0] * 12
    for row in (
        observations.annotate(month=ExtractMonth("observed_at", tzinfo=STOCKHOLM))
        .values("month")
        .annotate(observation_count=Count("pk"))
    ):
        months[row["month"] - 1] = row["observation_count"]
    return months


def _top_locales(observations) -> list[dict]:
    rows = (
        observations.filter(locale__isnull=False)
        .values("locale_id", "locale__name")
        .annotate(observation_count=Count("pk"))
        .order_by("-observation_count", "locale__name")[:TOP_LOCALE_LIMIT]
    )
    return [
        {"id": row["locale_id"], "name": row["locale__name"], "observation_count": row["observation_count"]}
        for row in rows
    ]


def _extremes(observations) -> dict | None:
    """The southernmost and northernmost observed positions and the distance
    between them, picked in the database."""
    positioned = (
        observations.filter(location__type="Point")
        .annotate(latitude=Cast(KT("location__coordinates__1"), FloatField()))
        .values_list("location__coordinates", "locale__name")
    )
    south = positioned.order_by("latitude", "pk").first()
    north = positioned.order_by("-latitude", "pk").first()
    if not south:
        return None
    (south_lon, south_lat), (north_lon, north_lat) = (
        [float(value) for value in south[0][:2]],
        [float(value) for value in north[0][:2]],
    )
    return {
        "south": {"coordinates": [south_lon, south_lat], "locale_name": south[1]},
        "north": {"coordinates": [north_lon, north_lat], "locale_name": north[1]},
        "distance_km": round(haversine_m(south_lat, south_lon, north_lat, north_lon) / 1000),
    }


def _follows(user) -> dict:
    """Followed species, and how many of them the user has observed."""
    return (
        SpeciesFollow.objects.filter(user=user)
        .annotate(
            seen=Exists(Observation.objects.filter(user=user, species_id=OuterRef("species_id")))
        )
        .aggregate(follow_count=Count("pk"), seen_count=Count("pk", filter=Q(seen=True)))
    )


def _planning(user) -> dict:
    """Checklists, how many of their species have an observation, and routes."""
    items = ChecklistItem.objects.filter(checklist__user=user).annotate(
        observed=Exists(
            Observation.checklist_items.through.objects.filter(checklistitem_id=OuterRef("pk"))
        )
    )
    return {
        "checklist_count": Checklist.objects.filter(user=user).count(),
        **items.aggregate(item_count=Count("pk"), observed_item_count=Count("pk", filter=Q(observed=True))),
        "route_count": Route.objects.filter(user=user).count(),
    }


def _birdnet(user) -> dict | None:
    """Detections from the user's BirdNET devices; None without a device."""
    if not BirdnetDevice.objects.filter(users=user).exists():
        return None
    return BirdnetDetection.objects.filter(device__users=user).aggregate(
        detection_count=Count("pk"),
        species_count=Count("scientific_name", distinct=True),
    )
