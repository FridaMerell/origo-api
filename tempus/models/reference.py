"""Small reference models used when describing species records."""

import uuid

from django.db import models


class Phenophase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)

    class Meta:
        ordering = ("label",)

    def __str__(self):
        return self.label


class Source(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    url = models.URLField()
    publisher = models.CharField(max_length=255)
    accessed_at = models.DateTimeField()

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title
