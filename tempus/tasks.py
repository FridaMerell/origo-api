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

from accounts.models import Notification
from django.db import transaction
from django.utils import timezone
from django_tasks import task

from tempus.services import artdatabanken, phenogram, route_planner

logger = logging.getLogger(__name__)


def enqueue_phenogram_generation(species_pk, geo_area_pk=None, *, years=None, refresh=True):
    """Queue at most one pending or running build for one (species, area).

    The durable ``PhenogramGeneration`` row is protected by a database unique
    constraint, so concurrent web processes cannot enqueue duplicate crawls.
    """
    from tempus.models import GeoArea, PhenogramGeneration, Species

    years = years or phenogram.DEFAULT_YEARS
    species = Species.objects.filter(pk=species_pk).first()
    if species is None:
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

        if not created and generation.status in {
            PhenogramGeneration.Status.PENDING,
            PhenogramGeneration.Status.RUNNING,
        }:
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
                registered_species_pks.append(str(species.pk))

    for species_pk in registered_species_pks:
        fan_out_species_phenograms.enqueue(species_pk)

    logger.info(
        "import_species_checklist(%s): registered %d, failed %d; phenograms queued",
        category_pk,
        len(registered_species_pks),
        len(failed_taxon_ids),
    )
    return {
        "registered": len(registered_species_pks),
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
    if generation is not None:
        with transaction.atomic():
            generation = PhenogramGeneration.objects.select_for_update().get(
                pk=generation.pk
            )
            if generation.status == PhenogramGeneration.Status.RUNNING:
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
    """Enqueue :func:`generate_phenogram` for this species across every GeoArea."""
    from tempus.models import GeoArea, Species

    if not Species.objects.filter(pk=species_pk).exists():
        return
    area_pks = [str(pk) for pk in GeoArea.objects.values_list("pk", flat=True)]
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
    species_pks = [str(pk) for pk in Species.objects.values_list("pk", flat=True)]
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
    from tempus.models import Phenogram, SpeciesFollow

    today = timezone.localdate()
    if today.weekday() != 6:
        days_until_sunday = (6 - today.weekday()) % 7 or 7
        notify_followed_species_season_start.using(
            run_after=timedelta(days=days_until_sunday)
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

        candidates_by_user.setdefault(follow.user, []).append(str(follow.species))

    created = 0
    prefix = "Fåglar som börjar komma i säsong inom 7-14 dagar enligt phenogrammet:"
    for user, species_names in candidates_by_user.items():
        recent_messages = Notification.objects.filter(
            user=user,
            domain="tempus",
            message__startswith=prefix,
            created_at__date__range=(today - timedelta(days=14), today),
        ).values_list("message", flat=True)
        previously_notified = {
            line[2:]
            for previous_message in recent_messages
            for line in previous_message.splitlines()
            if line.startswith("- ")
        }
        species_names = [
            name for name in species_names if name not in previously_notified
        ]
        if not species_names:
            continue

        message = prefix + "\n" + "\n".join(
            f"- {species_name}" for species_name in sorted(species_names)
        )
        already_sent = Notification.objects.filter(
            user=user,
            domain="tempus",
            message__startswith=prefix,
            created_at__date=today,
        ).exists()
        if not already_sent:
            Notification.objects.create(
                user=user,
                domain="tempus",
                message=message,
            )
            created += 1

    logger.info(
        "notify_followed_species_season_start: created %d notification(s)",
        created,
    )
    notify_followed_species_season_start.using(run_after=timedelta(days=7)).enqueue()
    return {"created": created}


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
    run.save(update_fields=["status", "started_at", "error"])

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
        run.save(update_fields=["status", "error", "finished_at"])
        logger.warning("compute_route_suggestions(%s) failed: %s", route_pk, exc)
        return
    except Exception as exc:
        run.status = RouteSuggestionRun.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        raise

    run.status = RouteSuggestionRun.SUCCEEDED
    run.result = stops
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "result", "finished_at"])
    logger.info(
        "compute_route_suggestions(%s): %d stop(s)", route_pk, len(stops)
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

    purge_birdnet_detections.using(run_after=BIRDNET_PURGE_INTERVAL).enqueue()
