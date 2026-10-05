"""Lexical entries used by annotations, their attested forms, and glossaries that collect them."""

from django.conf import settings
from django.db import models

from .planning import TextUnit


class LexicalEntry(models.Model):
    """A word or concept with linguistic attributes."""

    lemma = models.CharField(max_length=255)
    language = models.CharField(max_length=16)
    part_of_speech = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    inflection_data = models.JSONField(default=dict, blank=True)
    # A short gloss shown in a vocabulary quiz; ``definition`` holds the longer explanation.
    translation = models.CharField(max_length=255, blank=True)
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


class LexicalForm(models.Model):
    """A spelling variant or inflected form tied to an entry's base form.

    A form found in an older text can be linked to a modern lemma even when the
    reader is not sure of it, which ``is_uncertain`` records.
    """

    class Kind(models.TextChoices):
        SPELLING = "spelling", "Spelling variant"
        INFLECTION = "inflection", "Inflected form"

    entry = models.ForeignKey(LexicalEntry, on_delete=models.CASCADE, related_name="forms")
    form = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SPELLING)
    # Free text such as "pres. ind. 3 sg." for an inflected form.
    inflection = models.CharField(max_length=255, blank=True)
    is_uncertain = models.BooleanField(default=False)
    # Where the form was found, if anywhere in particular.
    unit = models.ForeignKey(
        TextUnit, on_delete=models.SET_NULL, related_name="lexical_forms", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry", "form", "id"]

    def __str__(self):
        return f"{self.form} → {self.entry}"


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
