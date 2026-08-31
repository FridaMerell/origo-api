"""Seed Flux with a small, repeatable dataset for local development."""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from flux.models import Milestone, Project, Task, Update


class Command(BaseCommand):
    help = "Create repeatable demo data for an existing Flux user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Username of the existing user who owns the seeded projects.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(
                f'No existing user was found with username "{options["username"]}".'
            )

        users = {"seed": user}
        projects = self._seed_projects(users)

        counts = {"projects": 0, "milestones": 0, "tasks": 0, "updates": 0}
        for project, project_data in projects:
            created = self._seed_project(project, project_data, users)
            for key, value in created.items():
                counts[key] += value

        self.stdout.write(
            self.style.SUCCESS(
                "Flux seed complete: "
                + ", ".join(f"{count} {name}" for name, count in counts.items())
                + "."
            )
        )

    def _seed_projects(self, users):
        project_data = [
            (
                "Flux Product Launch",
                "Plan and deliver the next Flux product release.",
                [users["seed"]],
            ),
            (
                "Flux API Reliability",
                "Improve observability, performance, and operational readiness.",
                [users["seed"]],
            ),
        ]

        projects = []
        for name, description, members in project_data:
            project, created = Project.objects.get_or_create(
                name=name,
                defaults={"description": description},
            )
            project.members.set(members)
            projects.append((project, {"description": description, "created": created, "members": members}))
        return projects

    def _seed_project(self, project, data, users):
        if project.description != data["description"]:
            project.description = data["description"]
            project.save(update_fields=["description", "updated_at"])

        counts = {
            "projects": int(data["created"]),
            "milestones": 0,
            "tasks": 0,
            "updates": 0,
        }
        today = date.today()

        planning, created = Milestone.objects.get_or_create(
            project=project,
            title="Planning",
            defaults={
                "description": "Align scope, owners, and delivery dates.",
                "status": Milestone.Status.DONE,
                "target_date": today - timedelta(days=7),
            },
        )
        counts["milestones"] += int(created)

        delivery, created = Milestone.objects.get_or_create(
            project=project,
            title="Delivery",
            defaults={
                "description": "Complete implementation and prepare the release.",
                "status": Milestone.Status.IN_PROGRESS,
                "target_date": today + timedelta(days=21),
            },
        )
        counts["milestones"] += int(created)

        kickoff, created = Task.objects.get_or_create(
            project=project,
            title="Kickoff and scope review",
            defaults={
                "milestone": planning,
                "description": "Review goals, risks, and the first delivery slice.",
                "due_date": today - timedelta(days=10),
                "priority": Task.Priority.HIGH,
                "status": Task.Status.DONE,
            },
        )
        kickoff.milestone = planning
        kickoff.assignees.set(data["members"])
        kickoff.save(update_fields=["milestone"])
        counts["tasks"] += int(created)

        implementation, created = Task.objects.get_or_create(
            project=project,
            title="Implement first delivery slice",
            defaults={
                "milestone": delivery,
                "description": "Build and review the first customer-facing slice.",
                "due_date": today + timedelta(days=14),
                "priority": Task.Priority.HIGH,
                "status": Task.Status.IN_PROGRESS,
            },
        )
        implementation.milestone = delivery
        implementation.assignees.set([users["seed"]])
        implementation.save(update_fields=["milestone"])
        implementation.requirements.set([kickoff])
        counts["tasks"] += int(created)

        follow_up, created = Task.objects.get_or_create(
            project=project,
            title="Send weekly project update",
            defaults={
                "milestone": delivery,
                "description": "Share progress, decisions, and blockers with stakeholders.",
                "due_date": today + timedelta(days=3),
                "recurrence": Task.Recurrence.WEEKLY,
                "recurrence_interval": 1,
                "recurrence_end_date": today + timedelta(days=28),
                "priority": Task.Priority.MEDIUM,
                "status": Task.Status.NOT_STARTED,
            },
        )
        follow_up.milestone = delivery
        follow_up.assignees.set([users["seed"]])
        follow_up.save(update_fields=["milestone"])
        counts["tasks"] += int(created)

        subtasks, created = Task.objects.get_or_create(
            project=project,
            title="Prepare release checklist",
            defaults={
                "milestone": delivery,
                "parent": implementation,
                "description": "Validate the release checklist before handoff.",
                "due_date": today + timedelta(days=10),
                "priority": Task.Priority.MEDIUM,
                "status": Task.Status.NOT_STARTED,
            },
        )
        subtasks.milestone = delivery
        subtasks.parent = implementation
        subtasks.assignees.set([users["seed"]])
        subtasks.save(update_fields=["milestone", "parent"])
        counts["tasks"] += int(created)

        updates = [
            ("Planning is complete and the delivery scope is agreed.", planning, kickoff, users["seed"]),
            ("Implementation is in progress; release checklist is the next checkpoint.", delivery, implementation, users["seed"]),
        ]
        for content, milestone, task, author in updates:
            _, created = Update.objects.get_or_create(
                project=project,
                content=content,
                defaults={"milestone": milestone, "task": task, "author": author},
            )
            counts["updates"] += int(created)

        return counts
