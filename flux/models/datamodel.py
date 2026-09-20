"""Structured data model of a project, used to scaffold code for several targets."""

from django.db import models

from .planning import Project


class Entity(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="entities")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "entities"
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="flux_entity_unique_name_per_project")]

    def __str__(self):
        return self.name


class Field(models.Model):
    class Type(models.TextChoices):
        STRING = "string", "String"
        TEXT = "text", "Text"
        INT = "int", "Integer"
        BIGINT = "bigint", "Big integer"
        DECIMAL = "decimal", "Decimal"
        FLOAT = "float", "Float"
        BOOL = "bool", "Boolean"
        DATE = "date", "Date"
        DATETIME = "datetime", "Date and time"
        TIME = "time", "Time"
        UUID = "uuid", "UUID"
        JSON = "json", "JSON"
        EMAIL = "email", "Email"
        URL = "url", "URL"

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.STRING)
    description = models.TextField(blank=True)
    nullable = models.BooleanField(default=False)
    unique = models.BooleanField(default=False)
    default = models.CharField(max_length=255, blank=True)
    max_length = models.PositiveIntegerField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["entity", "name"], name="flux_field_unique_name_per_entity")]

    def __str__(self):
        return f"{self.entity.name}.{self.name}"


class Relation(models.Model):
    class Kind(models.TextChoices):
        FOREIGN_KEY = "fk", "Foreign key"
        MANY_TO_MANY = "m2m", "Many to many"
        ONE_TO_ONE = "o2o", "One to one"

    class OnDelete(models.TextChoices):
        CASCADE = "cascade", "Cascade"
        PROTECT = "protect", "Protect"
        SET_NULL = "set_null", "Set null"

    source = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="outgoing_relations")
    target = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="incoming_relations")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FOREIGN_KEY)
    name = models.CharField(max_length=100)
    related_name = models.CharField(max_length=100, blank=True)
    on_delete = models.CharField(max_length=20, choices=OnDelete.choices, default=OnDelete.CASCADE)
    nullable = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["source", "name"], name="flux_relation_unique_name_per_source")]

    def __str__(self):
        return f"{self.source.name}.{self.name} -> {self.target.name}"
