"""Structured bibliography entries for authors."""

from django.db import models

from .people import Author


class BibliographyEntry(models.Model):
    """A curated or externally sourced bibliography entry for an author."""

    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="bibliography_entries")
    work = models.ForeignKey(
        "opus.Work", on_delete=models.SET_NULL, related_name="bibliography_entries", null=True, blank=True
    )
    title = models.CharField(max_length=500)
    year = models.CharField(max_length=100, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=16, blank=True)
    external_provider = models.CharField(max_length=50, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    note = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["author", "sort_order", "title", "id"]

    def __str__(self):
        return self.title
