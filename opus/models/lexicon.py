"""Lexical entries used by annotations, and glossaries that collect them."""

from django.conf import settings
from django.db import models


class LexicalEntry(models.Model):
    """A word or concept with linguistic attributes."""

    lemma = models.CharField(max_length=255)
    language = models.CharField(max_length=16)
    part_of_speech = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    inflection_data = models.JSONField(default=dict, blank=True)
    definition = models.TextField(blank=True)
    # Null for entries created before entries had owners.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opus_lexical_entries",
    )

    class Meta:
        ordering = ["lemma", "language", "id"]

    def __str__(self):
        return self.lemma


class Glossary(models.Model):
    """A word list, public or private to its owner like a work."""

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_glossaries"
    )
    is_private = models.BooleanField(default=False)
    entries = models.ManyToManyField(LexicalEntry, related_name="glossaries", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]
        verbose_name_plural = "glossaries"

    def __str__(self):
        return self.title
