"""Signal wiring for the tempus app (connected from ``TempusConfig.ready``).

Phenogram generation is normally fanned out to background tasks (see
:mod:`tempus.tasks`) whenever a new ``Species`` or a new ``GeoArea`` appears.
Checklist imports temporarily defer the species signal so they can create all
species before scheduling any phenograms. Enqueues use ``transaction.on_commit``
so rows are visible to the worker and rolled-back inserts enqueue nothing.

A separate receiver emits a PostgreSQL ``NOTIFY`` on commit for every new
``BirdnetDetection`` so the BirdNET SSE stream (:class:`tempus.views.
BirdnetDetectionStreamView`) can block on ``LISTEN`` instead of polling.
"""

import json
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from tempus.models import BIRDNET_DETECTION_CHANNEL, BirdnetDetection, GeoArea, Species
from tempus import tasks


_defer_species_phenograms = ContextVar(
    "tempus_defer_species_phenograms",
    default=False,
)


@contextmanager
def defer_species_phenograms():
    """Suppress automatic species fan-out within a staged bulk import."""
    token = _defer_species_phenograms.set(True)
    try:
        yield
    finally:
        _defer_species_phenograms.reset(token)


@receiver(post_save, sender=Species, dispatch_uid="tempus_species_phenograms")
def fan_out_species_phenograms_on_create(sender, instance, created, **kwargs):
    if created and not _defer_species_phenograms.get():
        transaction.on_commit(
            lambda: tasks.fan_out_species_phenograms.enqueue(str(instance.pk))
        )


@receiver(post_save, sender=GeoArea, dispatch_uid="tempus_area_phenograms")
def fan_out_area_phenograms_on_create(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: tasks.fan_out_area_phenograms.enqueue(str(instance.pk))
        )


@receiver(
    post_save,
    sender=BirdnetDetection,
    dispatch_uid="tempus_birdnet_detection_notify",
)
def notify_birdnet_detection(sender, instance, created, **kwargs):
    """Wake live SSE streams when a new detection commits (PostgreSQL only).

    ``bulk_create`` does not emit ``post_save`` and therefore does not notify;
    the device ingest path saves one row at a time and does. Non-PostgreSQL
    backends have no ``LISTEN``/``NOTIFY`` and the stream polls instead.
    """
    if not created or connection.vendor != "postgresql":
        return

    payload = json.dumps(
        {"id": str(instance.pk), "device_id": str(instance.device_id)}
    )

    def _emit():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_notify(%s, %s)", [BIRDNET_DETECTION_CHANNEL, payload]
            )

    transaction.on_commit(_emit)
