"""Background tasks for the tempus app (django-tasks / DEP 0014).

Phenogram generation is an expensive SOS crawl, so it never runs in a request.
The unit of work is :func:`generate_phenogram` - one (species, geo_area) curve.
:func:`fan_out_species_phenograms` and :func:`fan_out_area_phenograms` enqueue
one unit task per counterpart, so a single registration or a new GeoArea turns
into many small, independently retryable jobs.

Run a worker with ``python manage.py db_worker`` (or set
``TASKS_BACKEND=django_tasks.backends.immediate.ImmediateBackend`` to run
inline).
"""

import logging

from django_tasks import task

from tempus.services import artdatabanken, phenogram

logger = logging.getLogger(__name__)


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
