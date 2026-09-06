"""Background tasks for the flux app."""

import logging

from django_tasks import task

logger = logging.getLogger(__name__)


@task()
def create_next_recurring_task(task_pk):
    """Create the next instance for a completed recurring task."""
    from flux.models import Task

    task = Task.objects.filter(pk=task_pk).first()
    if task is None:
        return None
    if task.status != Task.Status.DONE:
        return None

    next_task = task.create_next_recurrence()
    if next_task is not None:
        logger.info(
            "create_next_recurring_task(%s): created task %s",
            task_pk,
            next_task.pk,
        )
        return str(next_task.pk)
    return None


@task()
def notify_flux_task_deadlines():
    """Notify assignees when an open Flux task is due today."""
    from datetime import timedelta

    from accounts.models import Notification
    from accounts.tasks import send_notification_email
    from django.utils import timezone
    from flux.models import Task

    today = timezone.localdate()
    due_tasks = (
        Task.objects.filter(due_date=today)
        .exclude(status=Task.Status.DONE)
        .select_related("project")
        .prefetch_related("assignees")
    )

    created = 0
    for flux_task in due_tasks:
        message = (
            f"Deadline idag: {flux_task.title}\n"
            f"Projekt: {flux_task.project.name}\n"
            f"Uppgifts-id: {flux_task.pk}"
        )
        for user in flux_task.assignees.all():
            already_notified = Notification.objects.filter(
                user=user,
                domain="flux",
                message=message,
                created_at__date=today,
            ).exists()
            if already_notified:
                continue

            notification = Notification.objects.create(
                user=user,
                domain="flux",
                message=message,
            )
            send_notification_email.enqueue(notification.pk)
            created += 1

    logger.info("notify_flux_task_deadlines: created %d notification(s)", created)
    notify_flux_task_deadlines.using(run_after=timedelta(days=1)).enqueue()
    return {"created": created}
