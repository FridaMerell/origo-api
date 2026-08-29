"""Signal wiring for the tempus app (connected from ``TempusConfig.ready``).

Phenogram generation is fanned out to background tasks (see
:mod:`tempus.tasks`) whenever a new ``Species`` or a new ``GeoArea`` appears.
The enqueue is deferred to ``transaction.on_commit`` so the row is visible to
the worker and a rolled-back insert enqueues nothing. django-tasks' own
``ENQUEUE_ON_COMMIT`` still applies on top.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from tempus.models import GeoArea, Species
from tempus import tasks


@receiver(post_save, sender=Species, dispatch_uid="tempus_species_phenograms")
def fan_out_species_phenograms_on_create(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: tasks.fan_out_species_phenograms.enqueue(instance.pk)
        )


@receiver(post_save, sender=GeoArea, dispatch_uid="tempus_area_phenograms")
def fan_out_area_phenograms_on_create(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: tasks.fan_out_area_phenograms.enqueue(str(instance.pk))
        )
