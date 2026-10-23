"""One user's year with Tempus: totals, months, places, species and photos.

Everything is aggregated in the database; only the rows the summary shows
leave it (one row per species, per distinct position and per photo shown).
Years follow Swedish local time, so a sighting just after midnight on New
Year's Eve counts towards the new year.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Count, Exists, F, Min, OuterRef, Subquery
from django.db.models.functions import ExtractMonth, ExtractYear

from tempus.models import Observation
from tempus.services.diversity import RED_LIST_BUMP
from tempus.services.geo import haversine_m
from tempus.services.route_planner import _redlist_code

STOCKHOLM = ZoneInfo("Europe/Stockholm")
PHOTO_LIMIT = 12


def _rarity(row: dict) -> float:
    """A species' rarity among its relatives with its red-list status added, as
    the route planner weighs it (``diversity.RED_LIST_BUMP``)."""
    return min(1.0, row["significance"] + RED_LIST_BUMP.get(row["red_list_category"], 0.0))


def observed_years(*, user: AbstractBaseUser) -> list[int]:
    """The years the user has observations in, newest first."""
    return list(
        Observation.objects.filter(user=user)
        .annotate(year=ExtractYear("observed_at", tzinfo=STOCKHOLM))
        .values_list("year", flat=True)
        .distinct()
        .order_by("-year")
    )


def year_summary(*, user: AbstractBaseUser, year: int) -> dict:
    start = datetime(year, 1, 1, tzinfo=STOCKHOLM)
    end = datetime(year + 1, 1, 1, tzinfo=STOCKHOLM)
    observations = Observation.objects.filter(
        user=user, observed_at__gte=start, observed_at__lt=end
    ).order_by()

    totals = observations.aggregate(
        observation_count=Count("pk"),
        species_count=Count("species", distinct=True),
        locale_count=Count("locale", distinct=True),
    )
    summary = {"year": year, "years": observed_years(user=user), **totals}
    if not totals["observation_count"]:
        return summary

    months = [0] * 12
    for row in (
        observations.annotate(month=ExtractMonth("observed_at", tzinfo=STOCKHOLM))
        .values("month")
        .annotate(observation_count=Count("pk"))
    ):
        months[row["month"] - 1] = row["observation_count"]

    species = _species_of_the_year(observations, user=user, start=start)
    points = _points(observations)
    top_locale = (
        observations.filter(locale__isnull=False)
        .values("locale_id", "locale__name")
        .annotate(observation_count=Count("pk"))
        .order_by("-observation_count", "locale__name")
        .first()
    )
    rated = [row for row in species if row["significance"] is not None]

    summary.update(
        months=months,
        first_observation=_first_observation(observations),
        species=species,
        new_species_count=sum(row["is_new"] for row in species),
        red_listed_count=sum(bool(row["red_list_category"]) for row in species),
        rarest=max(rated, key=_rarity) if rated else None,
        photos=_photos(observations),
        points=[point["coordinates"] for point in points],
        extremes=_extremes(points),
        top_locale=(
            {
                "id": top_locale["locale_id"],
                "name": top_locale["locale__name"],
                "observation_count": top_locale["observation_count"],
            }
            if top_locale
            else None
        ),
    )
    return summary


def _species_of_the_year(observations, *, user, start) -> list[dict]:
    """One row per species, in the order they were first seen during the year."""
    seen_before = Observation.objects.filter(
        user=user, species_id=OuterRef("species_id"), observed_at__lt=start
    )
    latest_photo = (
        observations.filter(species_id=OuterRef("species_id"))
        .exclude(photos=[])
        .order_by("-observed_at")
        .values("photos__0")[:1]
    )
    rows = (
        observations.values(
            "species_id",
            "species__dyntaxa_taxon_id",
            "species__swedish_name",
            "species__scientific_name",
            "species__significance",
            "species__api_data__redlistCategory",
        )
        .annotate(
            observation_count=Count("pk"),
            first_observed_at=Min("observed_at"),
            is_new=~Exists(seen_before),
            photo=Subquery(latest_photo),
        )
        .order_by("first_observed_at", "species__swedish_name")
    )
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
            "is_new": row["is_new"],
            "photo": row["photo"],
        }
        for row in rows
    ]


def _first_observation(observations) -> dict:
    first = (
        observations.select_related("species", "locale")
        .order_by("observed_at", "pk")
        .first()
    )
    return {
        "id": str(first.pk),
        "species_id": str(first.species_id),
        "swedish_name": first.species.swedish_name,
        "scientific_name": first.species.scientific_name,
        "observed_at": first.observed_at,
        "locale_name": first.locale.name if first.locale else None,
    }


def _photos(observations) -> list[dict]:
    """The year's photographed observations, the most significant species first."""
    rows = (
        observations.exclude(photos=[])
        .select_related("species", "locale")
        .order_by(F("species__significance").desc(nulls_last=True), "-observed_at", "pk")
        [:PHOTO_LIMIT]
    )
    return [
        {
            "observation_id": str(row.pk),
            "photo": row.photos[0],
            "species_id": str(row.species_id),
            "swedish_name": row.species.swedish_name,
            "scientific_name": row.species.scientific_name,
            "observed_at": row.observed_at,
            "locale_name": row.locale.name if row.locale else None,
        }
        for row in rows
    ]


def _points(observations) -> list[dict]:
    """Distinct observed positions, each with the locale it was logged to."""
    points = []
    for coordinates, locale_name in (
        observations.filter(location__type="Point")
        .values_list("location__coordinates", "locale__name")
        .distinct()
    ):
        try:
            lon, lat = float(coordinates[0]), float(coordinates[1])
        except (IndexError, TypeError, ValueError):
            continue
        points.append({"coordinates": [lon, lat], "locale_name": locale_name})
    return points


def _extremes(points: list[dict]) -> dict | None:
    """The southernmost and northernmost positions and the distance between them."""
    if not points:
        return None
    south = min(points, key=lambda point: point["coordinates"][1])
    north = max(points, key=lambda point: point["coordinates"][1])
    (south_lon, south_lat), (north_lon, north_lat) = south["coordinates"], north["coordinates"]
    return {
        "south": south,
        "north": north,
        "distance_km": round(haversine_m(south_lat, south_lon, north_lat, north_lon) / 1000),
    }
