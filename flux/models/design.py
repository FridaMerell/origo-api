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

    class AuthType(models.TextChoices):
        NONE = "none", "None"
        API_KEY_HEADER = "api_key_header", "API key in a header"
        API_KEY_QUERY = "api_key_query", "API key in the query string"
        BEARER = "bearer", "Bearer token"
        BASIC = "basic", "HTTP basic"
        OAUTH_CLIENT = "oauth_client", "OAuth client credentials"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="integrations")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.API)
    description = models.TextField(blank=True)
    env_vars = models.JSONField(default=list, blank=True, help_text="Names of required environment variables.")

    base_url = models.CharField(max_length=300, blank=True, help_text="Base URL of an inbound data API (https).")
    auth_type = models.CharField(max_length=20, choices=AuthType.choices, default=AuthType.NONE)
    auth_name = models.CharField(max_length=100, blank=True, help_text="Header or query parameter carrying an API key.")
    auth_env_var = models.CharField(max_length=100, blank=True, help_text="Env var with the key, token, username or client id.")
    auth_secret_env_var = models.CharField(max_length=100, blank=True, help_text="Env var with the password or client secret.")
    oauth_token_url = models.CharField(max_length=300, blank=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=30)
    retries = models.PositiveSmallIntegerField(default=2)
    rate_limit_per_minute = models.PositiveIntegerField(null=True, blank=True)
    cache_ttl_seconds = models.PositiveIntegerField(default=3600, help_text="Default cache time; 0 disables caching.")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="flux_integration_unique_name_per_project")
        ]

    def __str__(self):
        return self.name


class IntegrationOperation(models.Model):
    """One call against an inbound data API, optionally mapped onto an entity and synced."""

    class Method(models.TextChoices):
        GET = "GET", "GET"
        POST = "POST", "POST"

    class BodyFormat(models.TextChoices):
        JSON = "json", "JSON"
        FORM = "form", "Form"

    class Pagination(models.TextChoices):
        NONE = "none", "None"
        OFFSET = "offset", "Offset and limit"
        PAGE = "page", "Page number"
        CURSOR = "cursor", "Cursor"

    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="operations")
    name = models.CharField(max_length=60, help_text="Python identifier used for the generated function.")
    description = models.TextField(blank=True)
    method = models.CharField(max_length=4, choices=Method.choices, default=Method.GET)
    path = models.CharField(max_length=300, help_text="Path relative to base_url; {param} marks path parameters.")
    body_format = models.CharField(max_length=4, choices=BodyFormat.choices, default=BodyFormat.JSON)
    params = models.JSONField(default=list, blank=True, help_text="[{name, in, type, required, default, description}]")
    items_path = models.CharField(max_length=200, blank=True, help_text="Dotted path to the list in the response.")
    pagination = models.CharField(max_length=6, choices=Pagination.choices, default=Pagination.NONE)
    pagination_config = models.JSONField(default=dict, blank=True)
    filters = models.JSONField(default=list, blank=True, help_text="[{path, op, value}] applied to each item.")
    entity = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True, related_name="integration_operations")
    key_field = models.CharField(max_length=100, blank=True, help_text="Entity field that identifies a record when syncing.")
    mappings = models.JSONField(default=list, blank=True, help_text="[{path, field}] from an item to entity fields.")
    sync = models.BooleanField(default=False)
    sync_interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    cache_ttl_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Overrides the integration default.")
    sample_response = models.JSONField(null=True, blank=True, help_text="A real response captured from the live API.")

    class Meta:
        ordering = ["integration", "name"]
        constraints = [
            models.UniqueConstraint(fields=["integration", "name"], name="flux_integrationoperation_unique_name")
        ]

    def __str__(self):
        return f"{self.integration}.{self.name}"


class SeedRow(models.Model):
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="seed_rows")
    data = models.JSONField(default=dict)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["entity", "order", "id"]

    def __str__(self):
        return f"{self.entity} #{self.order}"
