"""Lexical entries used by annotations."""

from django.db import models


class LexicalEntry(models.Model):
    """A word or concept with linguistic attributes."""

    lemma = models.CharField(max_length=255)
    language = models.CharField(max_length=16)
    part_of_speech = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    inflection_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["lemma", "language", "id"]

    def __str__(self):
        return self.lemma
