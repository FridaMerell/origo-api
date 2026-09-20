"""Arbitrary documents for a house, e.g. maps, deeds, drawings, PDFs. Files are
hosted by the frontend; only their URLs are stored here."""

from django.conf import settings
from django.db import models

from .history import DatePrecision, Person
from .homes import House
from .photos import Tag
from .ventures import Venture


class Document(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="documents")
    venture = models.ForeignKey(Venture, on_delete=models.SET_NULL, related_name="documents", null=True, blank=True)
    tags = models.ManyToManyField(Tag, related_name="documents", blank=True)
    people = models.ManyToManyField(Person, related_name="documents", blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verso_documents")

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    url = models.URLField(max_length=2000)
    file_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField(null=True, blank=True)

    document_date = models.DateField(null=True, blank=True)
    date_precision = models.CharField(max_length=10, choices=DatePrecision.choices, default=DatePrecision.DAY)
    source = models.TextField(blank=True)
    # Plain-text transcription or extracted text, so the document is searchable.
    transcription = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
