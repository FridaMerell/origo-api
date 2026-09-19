from django.core.management.base import BaseCommand

from apsis.tasks import next_newsletter_run, send_weekly_apsis_newsletter


class Command(BaseCommand):
    help = "Schedule the first weekly Apsis newsletter run."

    def handle(self, *args, **options):
        next_run = next_newsletter_run()
        send_weekly_apsis_newsletter.using(run_after=next_run).enqueue()
        self.stdout.write(
            self.style.SUCCESS(
                f"Weekly Apsis newsletter scheduled for {next_run.isoformat()}."
            )
        )
