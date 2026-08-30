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
from datetime import timedelta

from django.utils import timezone
from django_tasks import task

from tempus.services import artdatabanken, phenogram, route_planner

logger = logging.getLogger(__name__)


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
    from tempus.models import GeoArea, Species

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

    kwargs = {"refresh": refresh}
    if years is not None:
        kwargs["years"] = years
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


@task()
def fan_out_species_phenograms(species_pk, *, refresh=True):
    """Enqueue :func:`generate_phenogram` for this species across every GeoArea."""
    from tempus.models import GeoArea, Species

    if not Species.objects.filter(pk=species_pk).exists():
        return
    area_pks = [str(pk) for pk in GeoArea.objects.values_list("pk", flat=True)]
    for area_pk in area_pks:
        generate_phenogram.enqueue(species_pk, area_pk, refresh=refresh)
    logger.info(
        "fan_out_species_phenograms(%s): enqueued %d area(s)",
        species_pk, len(area_pks),
    )


@task()
def fan_out_area_phenograms(geo_area_pk, *, refresh=True):
    """Enqueue :func:`generate_phenogram` for this GeoArea across every species."""
    from tempus.models import GeoArea, Species

    if not GeoArea.objects.filter(pk=geo_area_pk).exists():
        return
    species_pks = [str(pk) for pk in Species.objects.values_list("pk", flat=True)]
    for species_pk in species_pks:
        generate_phenogram.enqueue(species_pk, str(geo_area_pk), refresh=refresh)
    logger.info(
        "fan_out_area_phenograms(%s): enqueued %d species",
        geo_area_pk, len(species_pks),
    )


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
