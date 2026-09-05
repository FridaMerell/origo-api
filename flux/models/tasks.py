"""Tasks, dependencies, and recurrence rules."""

import calendar
from datetime import timedelta

from django.conf import settings
from django.db import models

from .planning import Milestone, Project


class Task(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    class Recurrence(models.TextChoices):
        NONE = "none", "None"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="subtasks")
    requirements = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="required_by")
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    recurrence = models.CharField(max_length=20, choices=Recurrence.choices, default=Recurrence.NONE)
    recurrence_interval = models.PositiveSmallIntegerField(default=1)
    recurrence_end_date = models.DateField(null=True, blank=True)
    recurrence_source = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="recurrence_occurrences")
    files = models.JSONField(blank=True, default=list)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    @property
    def is_recurring(self):
        return self.recurrence != self.Recurrence.NONE

    def next_recurrence_due_date(self):
        if not self.is_recurring or self.due_date is None:
            return None

        interval = max(self.recurrence_interval or 1, 1)
        if self.recurrence == self.Recurrence.DAILY:
            next_due_date = self.due_date + timedelta(days=interval)
        elif self.recurrence == self.Recurrence.WEEKLY:
            next_due_date = self.due_date + timedelta(weeks=interval)
        elif self.recurrence == self.Recurrence.MONTHLY:
            next_due_date = _add_months(self.due_date, interval)
        elif self.recurrence == self.Recurrence.YEARLY:
            next_due_date = _add_months(self.due_date, interval * 12)
        else:
            return None
        return None if self.recurrence_end_date and next_due_date > self.recurrence_end_date else next_due_date

    def create_next_recurrence(self):
        next_due_date = self.next_recurrence_due_date()
        if next_due_date is None:
            return None

        existing = self.recurrence_occurrences.order_by("created_at").first()
        if existing is not None:
            return existing

        next_task = Task.objects.create(
            project=self.project, milestone=self.milestone, parent=self.parent,
            title=self.title, description=self.description, due_date=next_due_date,
            recurrence=self.recurrence, recurrence_interval=max(self.recurrence_interval or 1, 1),
            recurrence_end_date=self.recurrence_end_date, recurrence_source=self,
            files=self.files, priority=self.priority, status=self.Status.NOT_STARTED,
        )
        next_task.requirements.set(self.requirements.all())
        next_task.assignees.set(self.assignees.all())
        return next_task


def _add_months(value, months):
    """Advance a date while clamping its day to the target month's last day."""
    target_month_index = value.month - 1 + months
    year = value.year + target_month_index // 12
    month = target_month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
