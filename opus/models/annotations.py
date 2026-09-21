"""User-owned annotations anchored to structured text."""

from django.conf import settings
from django.db import models

from .lexicon import LexicalEntry
from .planning import TextUnit


class Annotation(models.Model):
    """A highlight, definition, or marginal note on a text interval."""

    start_offset = models.PositiveIntegerField(null=True, blank=True)
    end_offset = models.PositiveIntegerField(null=True, blank=True)
    kind = models.CharField(max_length=20)
    body = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_annotations")
    unit = models.ForeignKey(TextUnit, on_delete=models.CASCADE, related_name="annotations")
    lexical_entry = models.ForeignKey(
        LexicalEntry, on_delete=models.SET_NULL, related_name="annotations", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["unit", "start_offset", "id"]

    def __str__(self):
        return f"{self.kind} on {self.unit}"
