"""House improvement projects, tasks, and progress updates."""

from django.conf import settings
from django.db import models

from .homes import House


class Venture(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.IntegerField(default=0)
    budget = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(blank=True, default=list)
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="ventures", null=True, blank=True)

    def __str__(self):
        return self.name


class VersoUpdate(models.Model):
    venture = models.ForeignKey(Venture, on_delete=models.CASCADE, related_name="updates", null=True, blank=True)
    task = models.ForeignKey("VentureTask", on_delete=models.CASCADE, related_name="updates", null=True, blank=True)
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="updates", null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verso_updates")
    title = models.CharField(max_length=255)
    content = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(blank=True, default=list)

    def __str__(self):
        venture_name = self.venture.name if self.venture else "N/A"
        task_name = self.task.name if self.task else "N/A"
        return f"Update: {self.title} for Venture: {venture_name} and Task: {task_name}"


class VentureTask(models.Model):
    venture = models.ForeignKey(Venture, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task: {self.name} for Venture: {self.venture.name}"
