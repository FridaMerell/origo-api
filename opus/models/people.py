"""People connected to literary works."""

from django.db import models


class Author(models.Model):
    """An author with biographical and bibliographical reference material."""

    name = models.CharField(max_length=255, unique=True)
    born = models.CharField(max_length=100, blank=True)
    died = models.CharField(max_length=100, blank=True)
    biography = models.TextField(blank=True)
    bibliography = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class AuthorAlias(models.Model):
    """A pseudonym, spelling variant, or transliteration of an author name."""

    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=255)
    language = models.CharField(max_length=16, blank=True)
    is_preferred = models.BooleanField(default=False)

    class Meta:
        ordering = ["author", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "name", "language"], name="opus_author_alias_unique"
            )
        ]

    def __str__(self):
        return self.name


class AuthorIdentifier(models.Model):
    """A stable external authority identifier for an author."""

    class Provider(models.TextChoices):
        WIKIDATA = "wikidata", "Wikidata"
        VIAF = "viaf", "VIAF"
        OPEN_LIBRARY = "openlibrary", "Open Library"
        LOC = "loc", "Library of Congress"

    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="identifiers")
    provider = models.CharField(max_length=50, choices=Provider.choices)
    external_id = models.CharField(max_length=255)
    external_url = models.URLField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["author", "provider", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "provider", "external_id"], name="opus_author_identifier_unique"
            )
        ]

    def __str__(self):
        return f"{self.author}: {self.provider}:{self.external_id}"


class WorkContributor(models.Model):
    """A person's role for a work, supporting multiple contributors."""

    class Role(models.TextChoices):
        AUTHOR = "author", "Author"
        EDITOR = "editor", "Editor"
        TRANSLATOR = "translator", "Translator"
        COMMENTATOR = "commentator", "Commentator"

    work = models.ForeignKey("opus.Work", on_delete=models.CASCADE, related_name="contributors")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="contributions")
    role = models.CharField(max_length=50, choices=Role.choices, default=Role.AUTHOR)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["work", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["work", "author", "role"], name="opus_work_contributor_unique"
            )
        ]
