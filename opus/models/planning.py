"""Works, imported editions, source files, and structured text."""

from django.conf import settings
from django.db import models


class Work(models.Model):
    """The abstract literary work, independent of a particular edition."""

    title = models.CharField(max_length=255)
    year = models.CharField(max_length=100, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_works"
    )
    is_private = models.BooleanField(default=False)
    shelves = models.ManyToManyField("Shelf", related_name="works", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]

    def __str__(self):
        return self.title


class Shelf(models.Model):
    """A reusable, loose library tag for grouping works."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Edition(models.Model):
    """An edition, transcription, modernization, or translation of a work."""

    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="editions")
    title = models.CharField(max_length=255)
    language = models.CharField(max_length=16)
    edition = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work", "title", "id"]

    def __str__(self):
        return f"{self.work}: {self.title}"


class SourceFile(models.Model):
    """Metadata for a document imported into an edition.

    The uploaded document itself is never persisted; extracted text is stored
    as ``TextUnit`` rows instead.
    """

    class ImportStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    version = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="source_files")
    storage_key = models.CharField(max_length=500, unique=True)
    original_filename = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, db_index=True)
    file_type = models.CharField(max_length=50)
    import_status = models.CharField(
        max_length=20, choices=ImportStatus.choices, default=ImportStatus.PENDING
    )
    failure_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["version", "id"]

    def __str__(self):
        return self.storage_key


class TextUnit(models.Model):
    """An ordered, hierarchical chapter, paragraph, or line."""

    class Kind(models.TextChoices):
        CHAPTER = "chapter", "Chapter"
        PARAGRAPH = "paragraph", "Paragraph"
        LINE = "line", "Line"

    version = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="text_units")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    position = models.PositiveIntegerField()
    content = models.TextField()
    label = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["version", "parent_id", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "parent", "position"],
                name="opus_textunit_unique_sibling_position",
            )
        ]

    def __str__(self):
        return self.label or f"{self.version} #{self.position}"
