import calendar
from datetime import timedelta

from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries
    tags = models.ManyToManyField('Tag', blank=True, related_name='projects')

    def __str__(self):
        return self.name


class Milestone(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not started'
        IN_PROGRESS = 'in_progress', 'In progress'
        DONE = 'done', 'Done'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='milestones')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED,
    )
    target_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries
    tags = models.ManyToManyField('Tag', blank=True, related_name='milestones')

    def __str__(self):
        return self.title


class Tag(models.Model):
    """A reusable label which can be applied to projects and milestones."""

    name = models.CharField(max_length=80)
    color = models.CharField(max_length=7, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='flux_tags',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['created_by', 'name'],
                name='flux_tag_unique_name_per_creator',
            ),
        ]
        ordering = ['name']

    def __str__(self):
        return self.name


class Document(models.Model):
    """Markdown documentation and Mermaid diagrams belonging to a Flux project."""

    class Kind(models.TextChoices):
        MARKDOWN = 'markdown', 'Markdown'
        FLOWCHART = 'flowchart', 'Flowchart'
        DATABASE_SCHEMA = 'database_schema', 'Database schema'

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='documents',
    )
    task = models.ForeignKey(
        'Task',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='documents',
    )
    title = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.MARKDOWN,
    )
    content = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='flux_documents',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title


class Task(models.Model):
    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not started'
        IN_PROGRESS = 'in_progress', 'In progress'
        DONE = 'done', 'Done'

    class Recurrence(models.TextChoices):
        NONE = 'none', 'None'
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'
        YEARLY = 'yearly', 'Yearly'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks',
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtasks',
    )
    requirements = models.ManyToManyField(
        'self', symmetrical=False, blank=True, related_name='required_by',
    )
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    recurrence = models.CharField(
        max_length=20, choices=Recurrence.choices, default=Recurrence.NONE,
    )
    recurrence_interval = models.PositiveSmallIntegerField(default=1)
    recurrence_end_date = models.DateField(null=True, blank=True)
    recurrence_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurrence_occurrences',
    )
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED,
    )
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

        if self.recurrence_end_date and next_due_date > self.recurrence_end_date:
            return None
        return next_due_date

    def create_next_recurrence(self):
        next_due_date = self.next_recurrence_due_date()
        if next_due_date is None:
            return None

        existing = self.recurrence_occurrences.order_by('created_at').first()
        if existing is not None:
            return existing

        next_task = Task.objects.create(
            project=self.project,
            milestone=self.milestone,
            parent=self.parent,
            title=self.title,
            description=self.description,
            due_date=next_due_date,
            recurrence=self.recurrence,
            recurrence_interval=max(self.recurrence_interval or 1, 1),
            recurrence_end_date=self.recurrence_end_date,
            recurrence_source=self,
            files=self.files,
            priority=self.priority,
            status=self.Status.NOT_STARTED,
        )
        next_task.requirements.set(self.requirements.all())
        next_task.assignees.set(self.assignees.all())
        return next_task


def _add_months(value, months):
    target_month_index = value.month - 1 + months
    year = value.year + target_month_index // 12
    month = target_month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


class Update(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='updates')
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name='updates',
    )
    task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='updates',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updates',
    )
    content = models.TextField()
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Update on {self.project} at {self.created_at}'
