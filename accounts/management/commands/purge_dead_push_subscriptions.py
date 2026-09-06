"""Delete Web Push subscriptions that have been inactive for a while."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import WebPushSubscription


class Command(BaseCommand):
    help = "Delete inactive (is_active=False) Web Push subscriptions older than N days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Age cutoff in days")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        deleted, _ = WebPushSubscription.objects.filter(
            is_active=False, created_at__lt=cutoff
        ).delete()
        self.stdout.write(f"Deleted {deleted} dead push subscription(s).")
