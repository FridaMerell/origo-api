"""Reading position, bookmarks, and saved excerpts."""

from django.conf import settings
from django.db import models

from .planning import Edition, TextUnit, Work


class ReadingProgress(models.Model):
    """The latest logical reading position for a user in a work."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_reading_progress")
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="reading_progress")
    position = models.PositiveIntegerField(default=0)
    character_index = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "work"], name="opus_reading_progress_per_user_work"
            )
        ]


class Bookmark(models.Model):
    """A user's saved position in an edition."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_bookmarks")
    version = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="bookmarks")
    unit = models.ForeignKey(TextUnit, on_delete=models.CASCADE, related_name="bookmarks")
    offset = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]


class Excerpt(models.Model):
    """A saved text excerpt with a source position and user metadata."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_excerpts")
    version = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="excerpts")
    unit = models.ForeignKey(TextUnit, on_delete=models.CASCADE, related_name="excerpts")
    start_offset = models.PositiveIntegerField(null=True, blank=True)
    end_offset = models.PositiveIntegerField(null=True, blank=True)
    text_snapshot = models.TextField()
    title = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]
