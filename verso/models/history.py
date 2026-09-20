"""History research for a house: people, events, and transcribed interviews.
Photos and maps come from ``Photo`` and are linked from here."""

from django.conf import settings
from django.db import models

from .homes import House


class DatePrecision(models.TextChoices):
    """How exact a historical date is; old material is rarely dated to the day."""

    DAY = "day", "Exact day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    DECADE = "decade", "Decade"
    CIRCA = "circa", "Approximately"


class Person(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="people")
    name = models.CharField(max_length=255)
    birth_date = models.DateField(null=True, blank=True)
    birth_date_precision = models.CharField(max_length=10, choices=DatePrecision.choices, default=DatePrecision.DAY)
    death_date = models.DateField(null=True, blank=True)
    death_date_precision = models.CharField(max_length=10, choices=DatePrecision.choices, default=DatePrecision.DAY)
    relation = models.CharField(max_length=255, blank=True)
    portrait = models.ForeignKey("Photo", on_delete=models.SET_NULL, related_name="+", null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people"

    def __str__(self):
        return self.name


class PersonRelation(models.Model):
    """A family tie between two people. For ``parent`` the tie is directed:
    ``person`` is the parent of ``related``. The other kinds are symmetric, so
    store each pair once."""

    class Kind(models.TextChoices):
        PARENT = "parent", "Parent of"
        SPOUSE = "spouse", "Spouse of"
        PARTNER = "partner", "Partner of"
        SIBLING = "sibling", "Sibling of"
        OTHER = "other", "Other"

    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="person_relations")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="relations_from")
    related = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="relations_to")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Free-text description of the tie, e.g. "adoptivson" or "fostersyster".
    label = models.CharField(max_length=100, blank=True)
    start_year = models.SmallIntegerField(null=True, blank=True)
    end_year = models.SmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["person", "related", "kind"], name="verso_unique_person_relation"),
            models.CheckConstraint(condition=~models.Q(person=models.F("related")), name="verso_relation_not_self"),
        ]

    def __str__(self):
        return f"{self.person} – {self.kind} – {self.related}"


class HistoryEvent(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="history_events")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    date_precision = models.CharField(max_length=10, choices=DatePrecision.choices, default=DatePrecision.YEAR)
    place = models.CharField(max_length=255, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    source = models.TextField(blank=True)
    # Plain text, e.g. a transcribed interview about the event.
    transcript = models.TextField(blank=True)
    people = models.ManyToManyField(Person, related_name="events", blank=True)
    photos = models.ManyToManyField("Photo", related_name="history_events", blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verso_history_events")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_start", "id"]

    def __str__(self):
        return self.title
