"""Create a private Flux project containing representative Codex plan data."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from flux.models import Document, Milestone, Project, Task, Update


class Command(BaseCommand):
    help = 'Create a private Flux seed project for one existing user.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            required=True,
            help='Username of the existing user who should own the seed project.',
        )
        parser.add_argument(
            '--name',
            default='Flux Codex seed',
            help='Name for the seed project.',
        )

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=options['username'])
        except user_model.DoesNotExist as exc:
            raise CommandError('No user exists with that username.') from exc

        today = timezone.localdate()
        with transaction.atomic():
            project = Project.objects.create(
                name=options['name'],
                description='Seed data for testing the Flux Codex plan integration.',
            )
            project.members.add(user)

            discovery = Milestone.objects.create(
                project=project,
                title='Discovery',
                description='Confirm scope and the delivery approach.',
                target_date=today + timedelta(days=7),
            )
            delivery = Milestone.objects.create(
                project=project,
                title='Delivery',
                description='Build, verify, and release the result.',
                target_date=today + timedelta(days=21),
            )

            brief = Task.objects.create(
                project=project,
                milestone=discovery,
                title='Write project brief',
                description='Define the problem, audience, and success criteria.',
                due_date=today + timedelta(days=3),
                priority=Task.Priority.HIGH,
            )
            Task.objects.create(
                project=project,
                milestone=delivery,
                parent=brief,
                title='Review brief with stakeholders',
                description='Capture decisions and any open questions.',
                due_date=today + timedelta(days=5),
            )
            Task.objects.create(
                project=project,
                milestone=delivery,
                title='Publish first release',
                description='Prepare the release and record its outcome.',
                due_date=today + timedelta(days=21),
                priority=Task.Priority.HIGH,
            )

            Document.objects.create(
                project=project,
                milestone=discovery,
                author=user,
                title='Project brief',
                kind=Document.Kind.MARKDOWN,
                content='# Project brief\n\nA representative Markdown document for Flux.',
            )
            Document.objects.create(
                project=project,
                milestone=delivery,
                author=user,
                title='Delivery flow',
                kind=Document.Kind.FLOWCHART,
                content='flowchart TD\nDiscovery --> Delivery\nDelivery --> Release',
            )
            Update.objects.create(
                project=project,
                milestone=discovery,
                task=brief,
                author=user,
                content='Seed project created for local Codex integration testing.',
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'Created private Flux seed project "{project.name}" (ID {project.id}) '
                f'for {user.username}.'
            )
        )
