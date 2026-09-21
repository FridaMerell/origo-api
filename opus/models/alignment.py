"""Interval-based alignment between editions."""

from django.conf import settings
from django.db import models

from .planning import Edition, TextUnit, Work


class AlignmentSet(models.Model):
    """A public or private alignment workspace for two or more editions."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="alignment_sets", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="opus_alignment_sets", null=True, blank=True
    )
    name = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(default=True)
    # Legacy pairwise anchors retained for backwards compatibility.
    source_version = models.ForeignKey(
        Edition, on_delete=models.CASCADE, related_name="source_alignment_sets", null=True, blank=True
    )
    target_version = models.ForeignKey(
        Edition, on_delete=models.CASCADE, related_name="target_alignment_sets", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work", "name", "id"]

    def __str__(self):
        return self.name or f"Alignment set #{self.pk}"


class AlignmentVersion(models.Model):
    """An edition included in a multi-edition alignment set."""

    alignment_set = models.ForeignKey(AlignmentSet, on_delete=models.CASCADE, related_name="editions")
    text_version = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="alignment_versions")
    display_order = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["alignment_set", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["alignment_set", "text_version"], name="opus_alignment_version_unique")
        ]


class AlignmentGroup(models.Model):
    """A shared reading position across all editions in a set."""

    alignment_set = models.ForeignKey(AlignmentSet, on_delete=models.CASCADE, related_name="groups")
    sequence = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["alignment_set", "sequence", "id"]


class AlignmentMember(models.Model):
    """The range from one edition that participates in an alignment group."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        OMITTED = "omitted", "Omitted"
        UNCERTAIN = "uncertain", "Uncertain"

    group = models.ForeignKey(AlignmentGroup, on_delete=models.CASCADE, related_name="members")
    alignment_version = models.ForeignKey(AlignmentVersion, on_delete=models.CASCADE, related_name="members")
    start_unit = models.ForeignKey(
        TextUnit, on_delete=models.SET_NULL, related_name="alignment_member_starts", null=True, blank=True
    )
    end_unit = models.ForeignKey(
        TextUnit, on_delete=models.SET_NULL, related_name="alignment_member_ends", null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)

    class Meta:
        ordering = ["group", "alignment_version", "id"]
        constraints = [
            models.UniqueConstraint(fields=["group", "alignment_version"], name="opus_alignment_member_unique")
        ]


class Alignment(models.Model):
    """A range-to-range correspondence between two editions."""

    class Type(models.TextChoices):
        EQUIVALENT = "equivalent", "Equivalent"
        PARTIAL = "partial", "Partial"
        OMITTED = "omitted", "Omitted"
        INSERTED = "inserted", "Inserted"
        UNCERTAIN = "uncertain", "Uncertain"

    source_start = models.CharField(max_length=255, null=True, blank=True)
    source_end = models.CharField(max_length=255, null=True, blank=True)
    target_start = models.CharField(max_length=255, null=True, blank=True)
    target_end = models.CharField(max_length=255, null=True, blank=True)
    alignment_type = models.CharField(max_length=20, choices=Type.choices)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    alignment_set = models.ForeignKey(
        AlignmentSet, on_delete=models.CASCADE, related_name="alignments"
    )
    source_unit = models.ForeignKey(
        TextUnit, on_delete=models.CASCADE, related_name="source_alignments", null=True, blank=True
    )
    target_unit = models.ForeignKey(
        TextUnit, on_delete=models.CASCADE, related_name="target_alignments", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["alignment_set", "id"]

    def __str__(self):
        return f"{self.alignment_set} ({self.alignment_type})"
