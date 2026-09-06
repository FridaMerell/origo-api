"""Send safe test emails for notification channels."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Notification, User
from accounts.tasks import send_notification_email


class Command(BaseCommand):
    help = "Send Flux and Tempus notification test emails for one recipient."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient email address")

    def handle(self, *args, **options):
        recipient = options["to"]
        user = User.objects.filter(email__iexact=recipient).first()
        if user is None:
            raise CommandError(f"No user exists with email address {recipient}.")

        tests = (
            (
                "flux",
                "flux_deadline",
                "[TEST] Deadline idag: Testa deadline-notifikationen i Origo.",
                {
                    "task_title": "Testa deadline-notifikationen",
                    "project_name": "Origo",
                    "task_id": "TEST",
                },
            ),
            (
                "tempus",
                "tempus_season",
                "[TEST] Snart i säsong: talgoxe och blåmes.",
                {"species_names": ["Talgoxe", "Blåmes"]},
            ),
        )
        for domain, template_key, message, context in tests:
            notification = Notification.objects.create(
                user=user,
                domain=domain,
                message=message,
            )
            result = send_notification_email.enqueue(
                notification.pk,
                template_key,
                context,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{domain}: created notification {notification.pk}; "
                    f"queued email task {result.id}"
                )
            )
