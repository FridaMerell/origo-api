"""Design inputs for scaffolding: stack, API resources, roles, screens, integrations and seed data."""

from django.db import models

from .datamodel import Entity
from .planning import Project


class StackProfile(models.Model):
    class ApiNaming(models.TextChoices):
        SNAKE_CASE = "snake_case", "snake_case"
        CAMEL_CASE = "camel_case", "camelCase"

    class AuthMethod(models.TextChoices):
        SESSION = "session", "Session"
        TOKEN = "token", "Token"
        JWT = "jwt", "JWT"
        NONE = "none", "None"

    class Database(models.TextChoices):
        POSTGRESQL = "postgresql", "PostgreSQL"
        MYSQL = "mysql", "MySQL"
        SQLITE = "sqlite", "SQLite"
        SQLSERVER = "sqlserver", "SQL Server"

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="stack_profile")
    targets = models.JSONField(default=list, blank=True, help_text="Any of: django, typescript, csharp.")
    api_naming = models.CharField(max_length=20, choices=ApiNaming.choices, default=ApiNaming.SNAKE_CASE)
    auth_method = models.CharField(max_length=20, choices=AuthMethod.choices, default=AuthMethod.SESSION)
    database = models.CharField(max_length=20, choices=Database.choices, default=Database.POSTGRESQL)
    app_label = models.CharField(max_length=100, blank=True, help_text="Django app label for generated models.")
    namespace = models.CharField(max_length=200, blank=True, help_text="C# root namespace.")

    def __str__(self):
        return f"Stack for {self.project}"


class Resource(models.Model):
    class Operation(models.TextChoices):
        LIST = "list", "List"
        RETRIEVE = "retrieve", "Retrieve"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"

    entity = models.OneToOneField(Entity, on_delete=models.CASCADE, related_name="resource")
    path = models.CharField(max_length=100)
    operations = models.JSONField(default=list, blank=True)
    filters = models.JSONField(default=list, blank=True, help_text="Field names usable as query filters.")
    ordering = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["path"]

    def __str__(self):
        return self.path


class Role(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="flux_role_unique_name_per_project")]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    class Scope(models.TextChoices):
        ALL = "all", "All"
        OWN = "own", "Own"
        MEMBER = "member", "Member"

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="role_permissions")
    operation = models.CharField(max_length=20, choices=Resource.Operation.choices)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.ALL)

    class Meta:
        ordering = ["role", "resource", "operation"]
        constraints = [
            models.UniqueConstraint(fields=["role", "resource", "operation"], name="flux_rolepermission_unique")
        ]

    def __str__(self):
        return f"{self.role} {self.operation} {self.resource} ({self.scope})"


class Screen(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="screens")
    name = models.CharField(max_length=100)
    route = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    entities = models.ManyToManyField(Entity, blank=True, related_name="screens")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")

    class Meta:
        ordering = ["route"]
        constraints = [models.UniqueConstraint(fields=["project", "route"], name="flux_screen_unique_route_per_project")]

    def __str__(self):
        return self.name


class Integration(models.Model):
    class Kind(models.TextChoices):
        API = "api", "External API"
        AUTH = "auth", "Authentication"
        STORAGE = "storage", "Storage"
        EMAIL = "email", "Email"
        PAYMENT = "payment", "Payment"
        OTHER = "other", "Other"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="integrations")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.API)
    description = models.TextField(blank=True)
    env_vars = models.JSONField(default=list, blank=True, help_text="Names of required environment variables.")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="flux_integration_unique_name_per_project")
        ]

    def __str__(self):
        return self.name


class SeedRow(models.Model):
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="seed_rows")
    data = models.JSONField(default=dict)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["entity", "order", "id"]

    def __str__(self):
        return f"{self.entity} #{self.order}"
