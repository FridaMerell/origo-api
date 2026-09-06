"""Queue safe test emails for notification channels."""

from django.core.management.base import BaseCommand

from accounts.tasks import send_notification_email_test


class Command(BaseCommand):
    help = "Queue Flux and Tempus notification test emails for one recipient."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient email address")

    def handle(self, *args, **options):
        recipient = options["to"]
        for domain in ("flux", "tempus"):
            send_notification_email_test.enqueue(domain, recipient)
        self.stdout.write(self.style.SUCCESS(f"Queued Flux and Tempus test emails for {recipient}."))
