"""Signal wiring for the flux app."""

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from flux import tasks
from flux.models import Task


@receiver(pre_save, sender=Task, dispatch_uid="flux_task_previous_status")
def remember_previous_task_status(sender, instance, raw=False, **kwargs):
    if raw:
        return
    if instance.pk is None:
        instance._previous_status = None
        return

    instance._previous_status = (
        Task.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    )


@receiver(post_save, sender=Task, dispatch_uid="flux_task_recurring_completion")
def schedule_next_recurring_task(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    became_done = instance.status == Task.Status.DONE and (
        created or getattr(instance, '_previous_status', None) != Task.Status.DONE
    )
    if became_done and instance.is_recurring:
        transaction.on_commit(
            lambda: tasks.create_next_recurring_task.enqueue(str(instance.pk))
        )
