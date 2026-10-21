"""Run every release-phase step in one Django process (Procfile ``release``)."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Migrate, create the cache table and ensure scheduled tasks in one process."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False)
        call_command("createcachetable")
        call_command("ensure_scheduled_tasks")
