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

from tempus.models import GeoArea, Observation, Phenogram
from tempus.services.diversity import RED_LIST_BUMP
from tempus.services.geo import haversine_m, point_in_multipolygon
from tempus.services.route_planner import _redlist_code

STOCKHOLM = ZoneInfo("Europe/Stockholm")
PHOTO_LIMIT = 12


def _bbox(geometry: dict) -> tuple[float, float, float, float] | None:
    """``(min_lon, min_lat, max_lon, max_lat)`` of a Polygon or MultiPolygon."""
    coords = (geometry or {}).get("coordinates") or []
    polygons = [coords] if geometry.get("type") == "Polygon" else coords
    points = [point for polygon in polygons for point in (polygon[0] if polygon else [])]
    if not points:
        return None
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lons), min(lats), max(lons), max(lats)


def rarest(observations, species: list[dict]) -> dict | None:
    """The species whose report stands out most where it was made.

    An observation counts with its species' significance for the province
    (landskap) it lies in (``Phenogram.significance``), or the whole-country
    value (``Species.significance``) when that province has none or the
    observation has no position; red-list status is added as the route planner
    weighs it (``diversity.RED_LIST_BUMP``). ``species`` is one row per species
    with ``id``, ``significance`` and ``red_list_category``; the winning row is
    returned with ``significance`` set to the value it won with.

    Candidates are tried highest value first, and each is checked only against
    its own species' positions, so most positions are never placed in a
    province.
    """
    by_id = {row["id"]: row for row in species}
    area_values: dict[str, dict[str, float]] = {}
    for species_id, area_id, value in (
        Phenogram.objects.filter(
            species_id__in=list(by_id),
            geo_area__kind=GeoArea.Kind.PROVINCE,
            significance__isnull=False,
            # Values from before the species-group measure have no group.
            significance_basis__has_key="group",
        )
        .order_by("computed_at")
        .values_list("species_id", "geo_area_id", "significance")
    ):
        area_values.setdefault(str(species_id), {})[str(area_id)] = value

    candidates = []
    for species_id, row in by_id.items():
        bump = RED_LIST_BUMP.get(row["red_list_category"], 0.0)
        for area_id, value in area_values.get(species_id, {}).items():
            candidates.append((min(1.0, value + bump), value, species_id, area_id))
        if row["significance"] is not None:
            candidates.append((min(1.0, row["significance"] + bump), row["significance"], species_id, None))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)

    # Positions of the species with a province value; an observation of one
    # without a usable position counts with the whole-country value.
    positions: dict[str, list[tuple[float, float]]] = {}
    unplaced = set()
    for species_id, kind, coordinates in (
        observations.filter(species_id__in=list(area_values))
        .values_list("species_id", "location__type", "location__coordinates")
        .distinct()
    ):
        try:
            if kind != "Point":
                raise ValueError
            point = (float(coordinates[0]), float(coordinates[1]))
        except (IndexError, TypeError, ValueError):
            unplaced.add(str(species_id))
            continue
        positions.setdefault(str(species_id), []).append(point)
    provinces = {
        str(area.pk): (area.geometry, _bbox(area.geometry))
        for area in GeoArea.objects.filter(kind=GeoArea.Kind.PROVINCE).only("pk", "geometry")
    }

    def inside(point, area_id) -> bool:
        geometry, bbox = provinces.get(area_id, (None, None))
        if bbox is None:
            return False
        lon, lat = point
        return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3] and point_in_multipolygon(point, geometry)

    for _, value, species_id, area_id in candidates:
        own = positions.get(species_id, [])
        rated = area_values.get(species_id, {})
        if area_id is not None:
            found = any(inside(point, area_id) for point in own)
        else:
            # The whole-country value counts for an observation outside every
            # province the species has a value for.
            found = (
                not rated
                or species_id in unplaced
                or any(not any(inside(point, rated_id) for rated_id in rated) for point in own)
            )
        if found:
            return {**by_id[species_id], "significance": value}
    return None


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
    summary.update(
        months=months,
        first_observation=_first_observation(observations),
        species=species,
        new_species_count=sum(row["is_new"] for row in species),
        red_listed_count=sum(bool(row["red_list_category"]) for row in species),
        rarest=rarest(observations, species),
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
        "dyntaxa_taxon_id": first.species.dyntaxa_taxon_id,
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
