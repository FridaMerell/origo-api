"""Background tasks for the tempus app (django-tasks / DEP 0014).

Phenogram generation is an expensive SOS crawl, so it never runs in a request.
The unit of work is :func:`generate_phenogram` - one (species, geo_area) curve.
:func:`fan_out_species_phenograms` and :func:`fan_out_area_phenograms` enqueue
one unit task per counterpart, so a single registration or a new GeoArea turns
into many small, independently retryable jobs.

Checklist imports are staged by :func:`import_species_checklist`: all species
are registered first, then phenogram fan-out is queued for the completed set.

Run a worker with ``python manage.py db_worker`` (or set
``TASKS_BACKEND=django_tasks.backends.immediate.ImmediateBackend`` to run
inline).
"""

import logging
import calendar
import datetime
from functools import partial
from datetime import timedelta
from zoneinfo import ZoneInfo

from accounts.models import Notification
from django.db import transaction
from django.utils import timezone
from django_tasks import task

from tempus.services import artdatabanken, lantmateriet, phenogram, route_planner
from tempus.services.locale_sources import SOURCES

logger = logging.getLogger(__name__)

LOCALE_LAND_COVER_BUFFER_METRES = 5000

# A pending/running row untouched for longer than this belongs to a worker that
# died; it no longer blocks a new run. The phenogram crawl can be slow.
GENERATION_STALE_AFTER = timedelta(hours=2)
RUN_STALE_AFTER = timedelta(minutes=30)
ACTIVE_RUN_STATUSES = ("pending", "running")


def run_is_hung(run, stale_after) -> bool:
    """Whether a pending/running row has not been updated within ``stale_after``."""
    return (
        run.status in ACTIVE_RUN_STATUSES
        and run.updated_at < timezone.now() - stale_after
    )


def fail_if_hung(run, stale_after=RUN_STALE_AFTER) -> bool:
    """Mark a hung ``RouteSuggestionRun``/``LandCoverFetch`` failed so pollers stop."""
    if not run_is_hung(run, stale_after):
        return False
    run.status = "failed"
    run.error = "Bakgrundskörningen avbröts innan den blev klar."
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at", "updated_at"])
    return True


def _has_swedish_name(species) -> bool:
    """Whether a species has a usable Swedish vernacular name."""
    return bool(species.swedish_name and species.swedish_name.strip())


def enqueue_phenogram_generation(species_pk, geo_area_pk=None, *, years=None, refresh=True):
    """Queue at most one pending or running build for one (species, area).

    The durable ``PhenogramGeneration`` row is protected by a database unique
    constraint, so concurrent web processes cannot enqueue duplicate crawls.
    """
    from tempus.models import GeoArea, PhenogramGeneration, Species

    years = years or phenogram.DEFAULT_YEARS
    species = Species.objects.filter(pk=species_pk).first()
    if species is None or not _has_swedish_name(species):
        return None, False
    geo_area = (
        GeoArea.objects.filter(pk=geo_area_pk).first()
        if geo_area_pk is not None
        else None
    )
    if geo_area_pk is not None and geo_area is None:
        return None, False

    lookup = {"species": species, "geo_area": geo_area}
    with transaction.atomic():
        generation = PhenogramGeneration.objects.select_for_update().filter(
            **lookup
        ).first()
        created = False
        if generation is None:
            generation, created = PhenogramGeneration.objects.get_or_create(
                **lookup, defaults={"years": years}
            )
            if not created:
                generation = PhenogramGeneration.objects.select_for_update().get(
                    **lookup
                )

        if (
            not created
            and generation.status in ACTIVE_RUN_STATUSES
            and not run_is_hung(generation, GENERATION_STALE_AFTER)
        ):
            return generation, False

        generation.status = PhenogramGeneration.Status.PENDING
        generation.years = years
        generation.error = ""
        generation.save(update_fields=["status", "years", "error", "updated_at"])
        transaction.on_commit(
            partial(
                generate_phenogram.enqueue,
                str(species.pk),
                str(geo_area.pk) if geo_area is not None else None,
                years=years,
                refresh=refresh,
            )
        )
    return generation, True


@task()
def import_species_checklist(category_pk, dyntaxa_taxon_ids):
    """Register a complete checklist, then schedule its phenograms.

    Individual API failures are logged and skipped so one unavailable taxon
    does not block the rest of the file. A missing API configuration still
    fails the task because it would prevent the whole batch from succeeding.
    """
    from tempus.models import SpeciesCategory
    from tempus.signals import defer_species_phenograms

    category = SpeciesCategory.objects.get(pk=category_pk)
    registered_species_pks = []
    failed_taxon_ids = []
    skipped_without_swedish_name = []

    with defer_species_phenograms():
        for taxon_id in dyntaxa_taxon_ids:
            try:
                species = artdatabanken.register_species(
                    category=category,
                    dyntaxa_taxon_id=taxon_id,
                )
            except artdatabanken.ArtdatabankenConfigurationError:
                logger.exception(
                    "import_species_checklist(category=%s) is not configured",
                    category_pk,
                )
                raise
            except artdatabanken.ArtdatabankenAPIError as exc:
                failed_taxon_ids.append(taxon_id)
                logger.warning(
                    "import_species_checklist(category=%s, taxon=%s) failed: %s",
                    category_pk,
                    taxon_id,
                    exc,
                )
            else:
                if species is None:
                    skipped_without_swedish_name.append(taxon_id)
                else:
                    registered_species_pks.append(str(species.pk))

    for species_pk in registered_species_pks:
        fan_out_species_phenograms.enqueue(species_pk)

    logger.info(
        "import_species_checklist(%s): registered %d, skipped without Swedish name %d, failed %d; phenograms queued",
        category_pk,
        len(registered_species_pks),
        len(skipped_without_swedish_name),
        len(failed_taxon_ids),
    )
    return {
        "registered": len(registered_species_pks),
        "skipped_without_swedish_name": skipped_without_swedish_name,
        "failed": failed_taxon_ids,
        "phenograms_scheduled": len(registered_species_pks),
    }


@task()
def register_species_from_api(category_pk, dyntaxa_taxon_id):
    """Download and register one checklist taxon under ``category_pk``."""
    from tempus.models import SpeciesCategory

    category = SpeciesCategory.objects.filter(pk=category_pk).first()
    if category is None:
        return
    try:
        artdatabanken.register_species(
            category=category,
            dyntaxa_taxon_id=dyntaxa_taxon_id,
        )
    except (
        artdatabanken.ArtdatabankenConfigurationError,
        artdatabanken.ArtdatabankenAPIError,
    ) as exc:
        logger.exception(
            "register_species_from_api(category=%s, taxon=%s) failed: %s",
            category_pk,
            dyntaxa_taxon_id,
            exc,
        )
        raise


@task()
def generate_phenogram(species_pk, geo_area_pk=None, *, years=None, refresh=True):
    """Build and store one phenogram for ``(species, geo_area)``.

    ``geo_area_pk=None`` is the whole-range curve. Swallows the two expected
    Artdatabanken failures so a worker does not spin on them; anything else
    propagates and django-tasks records the failure.
    """
    from tempus.models import GeoArea, PhenogramGeneration, Species

    # A deleted species or area also deletes its generation row (CASCADE).
    species = Species.objects.filter(pk=species_pk).first()
    if species is None:
        return
    geo_area = (
        GeoArea.objects.filter(pk=geo_area_pk).first()
        if geo_area_pk is not None
        else None
    )
    if geo_area_pk is not None and geo_area is None:
        return

    years = years or phenogram.DEFAULT_YEARS
    generation = PhenogramGeneration.objects.filter(
        species=species, geo_area=geo_area,
    ).first()
    if not _has_swedish_name(species):
        # Otherwise the row would stay pending and block every later enqueue.
        if generation is not None:
            generation.status = PhenogramGeneration.Status.FAILED
            generation.error = "The species has no Swedish name."
            generation.save(update_fields=["status", "error", "updated_at"])
        return
    if generation is not None:
        with transaction.atomic():
            generation = PhenogramGeneration.objects.select_for_update().get(
                pk=generation.pk
            )
            if (
                generation.status == PhenogramGeneration.Status.RUNNING
                and not run_is_hung(generation, GENERATION_STALE_AFTER)
            ):
                return
            generation.status = PhenogramGeneration.Status.RUNNING
            generation.error = ""
            generation.save(update_fields=["status", "error", "updated_at"])

    kwargs = {"refresh": refresh, "years": years}
    try:
        phenogram.get_phenogram(species, geo_area, **kwargs)
    except (
        artdatabanken.ArtdatabankenConfigurationError,
        artdatabanken.ArtdatabankenAPIError,
    ) as exc:
        logger.warning(
            "generate_phenogram(species=%s, geo_area=%s) skipped: %s",
            species_pk, geo_area_pk, exc,
        )
        if generation is not None:
            generation.status = PhenogramGeneration.Status.FAILED
            generation.error = str(exc)
            generation.save(update_fields=["status", "error", "updated_at"])
        return
    except Exception as exc:
        if generation is not None:
            generation.status = PhenogramGeneration.Status.FAILED
            generation.error = str(exc)
            generation.save(update_fields=["status", "error", "updated_at"])
        raise

    if generation is not None:
        generation.status = PhenogramGeneration.Status.SUCCEEDED
        generation.error = ""
        generation.save(update_fields=["status", "error", "updated_at"])


@task()
def fan_out_species_phenograms(species_pk, *, refresh=True):
    """Enqueue :func:`generate_phenogram` for this species: whole range + every GeoArea."""
    from tempus.models import GeoArea, Species

    species = Species.objects.filter(pk=species_pk).first()
    if species is None or not _has_swedish_name(species):
        return
    area_pks = [None, *(str(pk) for pk in GeoArea.objects.values_list("pk", flat=True))]
    queued = 0
    for area_pk in area_pks:
        _, created = enqueue_phenogram_generation(
            species_pk, area_pk, refresh=refresh,
        )
        queued += int(created)
    logger.info(
        "fan_out_species_phenograms(%s): enqueued %d of %d area(s)",
        species_pk, queued, len(area_pks),
    )


@task()
def fan_out_area_phenograms(geo_area_pk, *, refresh=True):
    """Enqueue :func:`generate_phenogram` for this GeoArea across every species."""
    from tempus.models import GeoArea, Species

    if not GeoArea.objects.filter(pk=geo_area_pk).exists():
        return
    species_pks = [
        str(species.pk)
        for species in Species.objects.only("pk", "swedish_name")
        if _has_swedish_name(species)
    ]
    queued = 0
    for species_pk in species_pks:
        _, created = enqueue_phenogram_generation(
            species_pk, str(geo_area_pk), refresh=refresh,
        )
        queued += int(created)
    logger.info(
        "fan_out_area_phenograms(%s): enqueued %d of %d species",
        geo_area_pk, queued, len(species_pks),
    )


def _day_of_year_to_date(day_of_year, year):
    """Map a phenogram day-of-year onto ``year`` safely around leap years."""
    last_day = 366 if calendar.isleap(year) else 365
    day_of_year = min(max(int(day_of_year), 1), last_day)
    return datetime.date(year, 1, 1) + timedelta(days=day_of_year - 1)


def _next_season_start_date(day_of_year, today):
    """Return the next calendar occurrence of a phenogram day-of-year."""
    candidate = _day_of_year_to_date(day_of_year, today.year)
    if candidate < today:
        candidate = _day_of_year_to_date(day_of_year, today.year + 1)
    return candidate


@task()
def notify_followed_species_season_start():
    """Notify followers on Sunday about species entering season in 7-14 days."""
    from accounts.tasks import send_notification_email
    from tempus.models import Phenogram, SpeciesFollow, SpeciesNotificationLog

    today = timezone.localdate()
    if today.weekday() != 6:
        days_until_sunday = (6 - today.weekday()) % 7 or 7
        notify_followed_species_season_start.using(
            run_after=timezone.now() + timedelta(days=days_until_sunday)
        ).enqueue()
        return {"created": 0, "skipped": "not_sunday"}

    follow_qs = SpeciesFollow.objects.filter(
        notifications_enabled=True,
    ).select_related("user", "species")
    species_ids = list(follow_qs.values_list("species_id", flat=True))
    phenograms = (
        Phenogram.objects.filter(
            species_id__in=species_ids,
            geo_area__isnull=True,
            record_count__gt=0,
        )
        .order_by("species_id", "-years")
    )
    latest_by_species = {}
    for row in phenograms:
        latest_by_species.setdefault(row.species_id, row)

    candidates_by_user = {}
    for follow in follow_qs:
        row = latest_by_species.get(follow.species_id)
        if row is None or row.start_day_of_year is None:
            continue
        season_start = _next_season_start_date(row.start_day_of_year, today)
        days_until_start = (season_start - today).days
        if not 7 <= days_until_start <= 14:
            continue

        candidates_by_user.setdefault(follow.user, []).append(
            (follow.species, season_start)
        )

    created = 0
    prefix = "Snart i säsong – följda arter vars phenogram börjar inom 7–14 dagar:"
    for user, candidates in candidates_by_user.items():
        # The log row is the record that this season was announced; it is
        # rolled back with the notification if creating that fails.
        with transaction.atomic():
            species_names = []
            for species, season_start in candidates:
                _, is_new = SpeciesNotificationLog.objects.get_or_create(
                    user=user,
                    species=species,
                    kind=SpeciesNotificationLog.Kind.SEASON_START,
                    period=season_start,
                )
                if is_new:
                    species_names.append(str(species))
            if not species_names:
                continue

            species_names.sort()
            message = prefix + "\n" + "\n".join(
                f"- {species_name}" for species_name in species_names
            )
            notification = Notification.objects.create(
                user=user,
                domain="tempus",
                message=message,
            )
            send_notification_email.enqueue(
                notification.pk,
                "tempus_season",
                {"species_names": species_names},
            )
            created += 1

    logger.info(
        "notify_followed_species_season_start: created %d notification(s)",
        created,
    )
    notify_followed_species_season_start.using(
        run_after=timezone.now() + timedelta(days=7)
    ).enqueue()
    return {"created": created}


# Artportalen dates are Swedish; the daily first-observation check runs at this
# hour and looks at the day before.
FIRST_OBSERVATION_TIME_ZONE = ZoneInfo("Europe/Stockholm")
FIRST_OBSERVATION_HOUR = 6
_FIRST_OBSERVATION_FIELDS = [
    "taxon.id", "event.plainStartDate", "location.locality", "location.municipality",
]


def next_first_observation_run(now=None):
    """Return the next ``FIRST_OBSERVATION_HOUR`` o'clock in Swedish time."""
    local_now = (now or timezone.now()).astimezone(FIRST_OBSERVATION_TIME_ZONE)
    next_run = local_now.replace(
        hour=FIRST_OBSERVATION_HOUR, minute=0, second=0, microsecond=0
    )
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


def _year_until_filter(day):
    return {
        "date": {
            "startDate": datetime.date(day.year, 1, 1).isoformat(),
            "endDate": day.isoformat(),
            "dateFilterType": "BetweenStartDateAndEndDate",
        },
        "occurrenceStatus": "Present",
    }


def first_observed_on(taxon_ids, day):
    """Return the taxon ids whose first Artportalen record of ``day``'s year is
    dated ``day``. One SOS ``TaxonAggregation`` call covers every taxon."""
    wanted = {int(taxon_id) for taxon_id in taxon_ids}
    if not wanted:
        return set()
    agg = artdatabanken.taxon_aggregation(
        {
            **_year_until_filter(day),
            "taxon": {"ids": sorted(wanted), "includeUnderlyingTaxa": True},
        },
        take=1000,
    )
    found = set()
    for record in (agg or {}).get("records") or []:
        taxon_id = record.get("taxonId")
        # firstSighting carries the Swedish offset, so its date part is the
        # date Artportalen shows.
        first = str(record.get("firstSighting") or "")[:10]
        if taxon_id is not None and int(taxon_id) in wanted and first == day.isoformat():
            found.add(int(taxon_id))
    return found


def first_observation_details(taxon_id, day):
    """Describe the year's first Artportalen record, e.g. "2026-04-01, Broby
    (Uppsala)". One search for the earliest record."""
    page = artdatabanken.search_observations(
        {
            **_year_until_filter(day),
            "taxon": {"ids": [int(taxon_id)], "includeUnderlyingTaxa": True},
            "output": {"fields": _FIRST_OBSERVATION_FIELDS},
        },
        take=1,
        sort_by="event.startDate",
        sort_order="Asc",
    )
    records = (page or {}).get("records") or []
    if not records:
        return day.isoformat()
    record = records[0]
    location = record.get("location") or {}
    parts = [(record.get("event") or {}).get("plainStartDate") or day.isoformat()]
    locality = (location.get("locality") or "").strip()
    municipality = location.get("municipality") or ""
    if isinstance(municipality, dict):
        municipality = municipality.get("name") or ""
    municipality = str(municipality).strip()
    if locality and municipality:
        parts.append(f"{locality} ({municipality})")
    elif locality or municipality:
        parts.append(locality or municipality)
    return ", ".join(parts)


@task()
def notify_first_observation_of_year():
    """Each morning, tell followers about species whose first Artportalen
    record of the year is dated yesterday."""
    yesterday = (
        timezone.now().astimezone(FIRST_OBSERVATION_TIME_ZONE).date()
        - timedelta(days=1)
    )
    try:
        created = _notify_first_observations(yesterday)
    finally:
        notify_first_observation_of_year.using(
            run_after=next_first_observation_run()
        ).enqueue()
    logger.info(
        "notify_first_observation_of_year(%s): created %d notification(s)",
        yesterday, created,
    )
    return {"created": created}


def _notify_first_observations(day):
    from accounts.tasks import send_notification_email
    from tempus.models import SpeciesFollow, SpeciesNotificationLog

    year_start = datetime.date(day.year, 1, 1)
    follows_by_taxon = {}
    for follow in SpeciesFollow.objects.filter(
        notifications_enabled=True,
        species__dyntaxa_taxon_id__isnull=False,
    ).select_related("species"):
        follows_by_taxon.setdefault(follow.species.dyntaxa_taxon_id, []).append(follow)

    created = 0
    for taxon_id in first_observed_on(follows_by_taxon, day):
        taxon_follows = follows_by_taxon[taxon_id]
        species_name = str(taxon_follows[0].species)
        message = (
            f"Årets första obs av {species_name} i Artportalen: "
            f"{first_observation_details(taxon_id, day)}."
        )
        for follow in taxon_follows:
            # A rerun of the same day (or a duplicate chain) finds the log row
            # and sends nothing.
            with transaction.atomic():
                _, is_new = SpeciesNotificationLog.objects.get_or_create(
                    user_id=follow.user_id,
                    species_id=follow.species_id,
                    kind=SpeciesNotificationLog.Kind.FIRST_OBSERVATION,
                    period=year_start,
                )
                if not is_new:
                    continue
                notification = Notification.objects.create(
                    user_id=follow.user_id,
                    domain="tempus",
                    message=message,
                )
                send_notification_email.enqueue(
                    notification.pk,
                    "tempus_first_observation",
                    {"species_name": species_name},
                )
                created += 1
    return created


@task()
def compute_route_suggestions(route_pk):
    """Compute this route's rest-stop suggestions and store them on its
    ``RouteSuggestionRun`` row (which the frontend polls).

    One row per route: the result is overwritten in place. Expected
    Artdatabanken failures land on the row as ``status="failed"`` with a
    message; anything unexpected also marks the row failed and then propagates
    so django-tasks records it.
    """
    from tempus.models import Route, RouteSuggestionRun

    route = Route.objects.filter(pk=route_pk).first()
    if route is None:
        return
    run, _ = RouteSuggestionRun.objects.get_or_create(route=route)

    run.status = RouteSuggestionRun.RUNNING
    run.started_at = timezone.now()
    run.error = ""
    run.save(update_fields=["status", "started_at", "error", "updated_at"])

    try:
        stops = route_planner.suggest_rest_stops(
            route.geometry, route.corridor_metres, **(run.params or {})
        )
    except (
        ValueError,
        artdatabanken.ArtdatabankenConfigurationError,
        artdatabanken.ArtdatabankenAPIError,
    ) as exc:
        run.status = RouteSuggestionRun.FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at", "updated_at"])
        logger.warning("compute_route_suggestions(%s) failed: %s", route_pk, exc)
        return
    except Exception as exc:
        run.status = RouteSuggestionRun.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at", "updated_at"])
        raise

    run.status = RouteSuggestionRun.SUCCEEDED
    run.result = stops
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "result", "finished_at", "updated_at"])
    logger.info(
        "compute_route_suggestions(%s): %d stop(s)", route_pk, len(stops)
    )


@task()
def fetch_locale_land_cover(locale_pk, *, buffer_metres=LOCALE_LAND_COVER_BUFFER_METRES):
    """Prefetch this Locale's padded area from every source in ``locale_sources.SOURCES``.

    One ``LandCoverFetch`` row per Locale (like ``RouteSuggestionRun`` per
    Route): the result is overwritten in place on every run. The fetched area
    is the Locale's own bounding box padded by ``buffer_metres`` in every
    direction, separate from and not consumed by the existing exact-boundary
    ``/locales/{id}/land-cover/map/`` endpoint. All sources are fetched
    together as one unit: either every field is refreshed, or - on failure -
    none of the previous results are overwritten. The padded bbox/geometry
    below is computed once (``lantmateriet.buffered_bbox``) and shared across
    every source's fetch call.

    Skips both calls when the previous successful fetch's area already covers
    the locale's current padded bounding box, so a save that does not move
    the boundary (renaming, editing an unrelated field) does not re-fetch data
    it already has. A boundary edit that grows or shifts the box always
    leaves some of the new box uncovered, so it always re-fetches.
    """
    from shapely.geometry import box, mapping, shape

    from tempus.models import LandCoverFetch, Locale

    locale = Locale.objects.filter(pk=locale_pk).first()
    if locale is None:
        return
    fetch, _ = LandCoverFetch.objects.get_or_create(locale=locale)

    bbox = lantmateriet.buffered_bbox(locale.geometry, buffer_metres)
    needed_shape = box(*bbox)
    if fetch.status == LandCoverFetch.SUCCEEDED and fetch.geometry:
        try:
            already_covered = shape(fetch.geometry).covers(needed_shape)
        except (TypeError, ValueError, KeyError):
            already_covered = False
        if already_covered:
            logger.info(
                "fetch_locale_land_cover(%s): already covers the current area, skipping",
                locale_pk,
            )
            return

    fetch.status = LandCoverFetch.RUNNING
    fetch.buffer_metres = buffer_metres
    fetch.started_at = timezone.now()
    fetch.error = ""
    fetch.save(update_fields=["status", "buffer_metres", "started_at", "error", "updated_at"])

    needed_geometry = mapping(needed_shape)
    try:
        results = {
            source.field: source.fetch(needed_geometry, bbox) for source in SOURCES
        }
    except (
        lantmateriet.LantmaterietConfigurationError,
        lantmateriet.LantmaterietAPIError,
    ) as exc:
        fetch.status = LandCoverFetch.FAILED
        fetch.error = str(exc)
        fetch.finished_at = timezone.now()
        fetch.save(update_fields=["status", "error", "finished_at", "updated_at"])
        logger.warning("fetch_locale_land_cover(%s) failed: %s", locale_pk, exc)
        return
    except Exception as exc:
        fetch.status = LandCoverFetch.FAILED
        fetch.error = f"{type(exc).__name__}: {exc}"
        fetch.finished_at = timezone.now()
        fetch.save(update_fields=["status", "error", "finished_at", "updated_at"])
        raise

    fetch.geometry = needed_geometry
    fetch.status = LandCoverFetch.SUCCEEDED
    for field, value in results.items():
        setattr(fetch, field, value)
    fetch.finished_at = timezone.now()
    fetch.save(
        update_fields=["geometry", "status", "finished_at", "updated_at", *results.keys()]
    )
    logger.info(
        "fetch_locale_land_cover(%s): %s",
        locale_pk,
        ", ".join(
            f"{len(results[source.field].get('features', []))} {source.key}"
            for source in SOURCES
        ),
    )


BIRDNET_RETENTION = timedelta(hours=24)
BIRDNET_PURGE_INTERVAL = timedelta(hours=1)


@task()
def purge_birdnet_detections():
    """Delete BirdNET detections past their 24h retention, then reschedule.

    Self-scheduling: each run re-enqueues itself ``BIRDNET_PURGE_INTERVAL``
    later, so enqueueing it once (e.g. after deploy) keeps it running. Extra
    enqueues are harmless - a run only deletes and reschedules.
    """
    from tempus.models import BirdnetDetection

    cutoff = timezone.now() - BIRDNET_RETENTION
    deleted, _ = BirdnetDetection.objects.filter(detected_at__lt=cutoff).delete()
    logger.info("purge_birdnet_detections: deleted %d row(s)", deleted)

    purge_birdnet_detections.using(
        run_after=timezone.now() + BIRDNET_PURGE_INTERVAL
    ).enqueue()
