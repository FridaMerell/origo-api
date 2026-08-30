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
