"""Ensure recurring notification and maintenance tasks have an active chain."""

from django.core.management.base import BaseCommand

from django_tasks_db.models import DBTaskResult

from accounts.tasks import purge_dead_web_push_subscriptions
from apsis.tasks import next_newsletter_run, send_weekly_apsis_newsletter
from flux.tasks import notify_flux_task_deadlines
from tempus.tasks import notify_followed_species_season_start, purge_birdnet_detections


ACTIVE_STATUSES = ("READY", "RUNNING")


class Command(BaseCommand):
    help = "Ensure recurring notification and maintenance task chains are scheduled."

    def _ensure(self, task, *, run_after=None):
        task_path = task.module_path
        active = DBTaskResult.objects.filter(
            task_path=task_path,
            status__in=ACTIVE_STATUSES,
        ).exists()
        if active:
            self.stdout.write(f"Already active: {task_path}")
            return False

        scheduled = task.using(run_after=run_after) if run_after is not None else task
        result = scheduled.enqueue()
        self.stdout.write(f"Scheduled: {task_path} ({result.id})")
        return True

    def handle(self, *args, **options):
        self._ensure(notify_flux_task_deadlines)
        self._ensure(notify_followed_species_season_start)
        self._ensure(
            send_weekly_apsis_newsletter,
            run_after=next_newsletter_run(),
        )
        self._ensure(purge_dead_web_push_subscriptions)
        self._ensure(purge_birdnet_detections)
