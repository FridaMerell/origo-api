from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries

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
