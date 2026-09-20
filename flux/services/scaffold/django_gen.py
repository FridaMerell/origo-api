"""Django target: models, DRF serializers/viewsets/urls, role matrix and fixtures."""

import json
from decimal import Decimal, InvalidOperation

from .common import app_label, pascal, snake

_FIELD_CLASSES = {
    "string": "CharField",
    "text": "TextField",
    "int": "IntegerField",
    "bigint": "BigIntegerField",
    "decimal": "DecimalField",
    "float": "FloatField",
    "bool": "BooleanField",
    "date": "DateField",
    "datetime": "DateTimeField",
    "time": "TimeField",
    "uuid": "UUIDField",
    "json": "JSONField",
    "email": "EmailField",
    "url": "URLField",
}
_TEXT_TYPES = {"string", "text", "email", "url"}
_ON_DELETE = {"cascade": "CASCADE", "protect": "PROTECT", "set_null": "SET_NULL"}
_OPERATION_MIXINS = {
    "list": "ListModelMixin",
    "retrieve": "RetrieveModelMixin",
    "create": "CreateModelMixin",
    "update": "UpdateModelMixin",
    "delete": "DestroyModelMixin",
}
_ACTION_OPERATIONS = {
    "GET": "list",
    "HEAD": "list",
    "OPTIONS": "list",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def _default_literal(field):
    raw = field.get("default") or ""
    if raw == "":
        return None, None
    kind = field["type"]
    if kind in _TEXT_TYPES:
        return repr(raw), None
    if kind == "bool":
        return ("True" if raw.lower() in ("true", "1", "yes") else "False"), None
    if kind in ("int", "bigint"):
        return str(int(raw)), None
    if kind == "float":
        return str(float(raw)), None
    if kind == "decimal":
        try:
            Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid decimal default {raw!r} for field {field['name']}.") from exc
        return f"Decimal({raw!r})", "from decimal import Decimal"
    if kind == "datetime" and raw == "now":
        return "timezone.now", "from django.utils import timezone"
    if kind == "uuid" and raw == "uuid4":
        return "uuid.uuid4", "import uuid"
    if kind == "json" and raw in ("{}", "[]"):
        return ("dict" if raw == "{}" else "list"), None
    raise ValueError(f"Unsupported default {raw!r} for field {field['name']} of type {kind}.")


def _field_line(field, imports):
    args = []
    kind = field["type"]
    if kind == "string":
        args.append(f"max_length={field.get('max_length') or 255}")
    if kind == "decimal":
        args.extend(["max_digits=12", "decimal_places=2"])
    if field.get("unique"):
        args.append("unique=True")
    if field.get("nullable"):
        args.extend(["null=True", "blank=True"])
    default, import_line = _default_literal(field)
    if default is not None:
        args.append(f"default={default}")
        if import_line:
            imports.add(import_line)
    return f"    {snake(field['name'])} = models.{_FIELD_CLASSES[kind]}({', '.join(args)})"


def _relation_line(relation, source_name, siblings):
    kind = relation["kind"]
    related_name = relation.get("related_name")
    if not related_name and sum(1 for other in siblings if other["target"] == relation["target"]) > 1:
        related_name = f"{snake(source_name)}_{snake(relation['name'])}_set"
    class_name = {"fk": "ForeignKey", "m2m": "ManyToManyField", "o2o": "OneToOneField"}[kind]
    args = [repr(pascal(relation["target"]))]
    nullable = relation.get("nullable")
    if kind != "m2m":
        on_delete = relation.get("on_delete", "cascade")
        args.append(f"on_delete=models.{_ON_DELETE[on_delete]}")
        nullable = nullable or on_delete == "set_null"
    if related_name:
        args.append(f"related_name={related_name!r}")
    if kind == "m2m":
        args.append("blank=True")
    elif nullable:
        args.extend(["null=True", "blank=True"])
    return f"    {snake(relation['name'])} = models.{class_name}({', '.join(args)})"


def _model_source(entity):
    imports = set()
    lines = [f"class {pascal(entity['name'])}(models.Model):"]
    if entity.get("description"):
        lines.append(f'    """{entity["description"].strip().splitlines()[0]}"""')
        lines.append("")
    body = [_field_line(field, imports) for field in entity["fields"]]
    body += [_relation_line(relation, entity["name"], entity["relations"]) for relation in entity["relations"]]
    lines += body or ["    pass"]
    label = next((f for f in entity["fields"] if f["name"] in ("name", "title")), None)
    lines += ["", "    def __str__(self):"]
    lines.append(f"        return str(self.{snake(label['name'])})" if label else "        return str(self.pk)")
    return imports, "\n".join(lines)


def models_file(spec):
    imports, classes = set(), []
    for entity in spec["entities"]:
        entity_imports, source = _model_source(entity)
        imports |= entity_imports
        classes.append(source)
    stdlib = sorted(line for line in imports if not line.startswith("from django"))
    django = sorted({"from django.db import models"} | {line for line in imports if line.startswith("from django")})
    header = "\n".join(stdlib) + ("\n\n" if stdlib else "") + "\n".join(django)
    return header + "\n\n\n" + "\n\n\n".join(classes) + "\n"


def serializers_file(spec):
    entities = [pascal(resource["entity"]) for resource in spec["resources"]]
    lines = ["from rest_framework import serializers", "", f"from .models import {', '.join(entities)}", ""]
    for name in entities:
        lines += [
            "",
            f"class {name}Serializer(serializers.ModelSerializer):",
            "    class Meta:",
            f"        model = {name}",
            '        fields = "__all__"',
            "",
        ]
    return "\n".join(lines)


def views_file(spec):
    has_roles = bool(spec["roles"])
    names = [pascal(resource["entity"]) for resource in spec["resources"]]
    lines = ["from rest_framework import mixins, permissions, viewsets", ""]
    lines.append(f"from .models import {', '.join(names)}")
    lines.append(f"from .serializers import {', '.join(f'{n}Serializer' for n in names)}")
    if has_roles:
        lines.append("from .permissions import RolePermission")
    for resource in spec["resources"]:
        name = pascal(resource["entity"])
        bases = [f"mixins.{_OPERATION_MIXINS[op]}" for op in _ordered(resource["operations"])]
        base_permission = "permissions.AllowAny" if spec["stack"]["auth_method"] == "none" else "permissions.IsAuthenticated"
        permission_classes = f"{base_permission}, RolePermission" if has_roles else base_permission
        lines += [
            "",
            "",
            f"class {name}ViewSet({', '.join(bases + ['viewsets.GenericViewSet'])}):",
            f"    queryset = {name}.objects.all()",
            f"    serializer_class = {name}Serializer",
            f"    permission_classes = [{permission_classes}]",
        ]
        if has_roles:
            lines.append(f"    resource = {resource['entity']!r}")
        if resource.get("filters"):
            lines.append(f"    filterset_fields = {[snake(f) for f in resource['filters']]!r}")
        if resource.get("ordering"):
            lines.append(f"    ordering = [{resource['ordering']!r}]")
    return "\n".join(lines) + "\n"


def _ordered(operations):
    order = list(_OPERATION_MIXINS)
    return [op for op in order if op in operations]


def urls_file(spec):
    names = [pascal(resource["entity"]) for resource in spec["resources"]]
    lines = [
        "from rest_framework.routers import DefaultRouter",
        "",
        f"from .views import {', '.join(f'{n}ViewSet' for n in names)}",
        "",
        "router = DefaultRouter()",
    ]
    for resource in spec["resources"]:
        name = pascal(resource["entity"])
        lines.append(f"router.register({resource['path'].strip('/')!r}, {name}ViewSet, basename={snake(resource['entity'])!r})")
    lines += ["", "urlpatterns = router.urls", ""]
    return "\n".join(lines)


def permissions_file(spec):
    matrix = {}
    for role in spec["roles"]:
        for permission in role["permissions"]:
            matrix.setdefault(role["name"], {}).setdefault(permission["resource"], {})[permission["operation"]] = permission["scope"]
    return (
        "from rest_framework.permissions import BasePermission\n\n"
        "# role -> resource -> operation -> scope (all / own / member)\n"
        f"ROLE_PERMISSIONS = {json.dumps(matrix, indent=4)}\n\n"
        f"ACTION_OPERATIONS = {json.dumps(_ACTION_OPERATIONS, indent=4)}\n\n\n"
        "def scope_for(role, resource, operation):\n"
        "    return ROLE_PERMISSIONS.get(role, {}).get(resource, {}).get(operation)\n\n\n"
        "class RolePermission(BasePermission):\n"
        '    """Allow a request when the user\'s role grants the operation on the view\'s resource.\n\n'
        "    Reads the role from ``request.user.role``; enforce the scope in ``get_queryset``.\n"
        '    """\n\n'
        "    def has_permission(self, request, view):\n"
        "        role = getattr(request.user, 'role', None)\n"
        "        operation = getattr(view, 'action', None)\n"
        "        if operation == 'partial_update':\n"
        "            operation = 'update'\n"
        "        if operation is None:\n"
        "            operation = ACTION_OPERATIONS.get(request.method)\n"
        "        return scope_for(role, getattr(view, 'resource', None), operation) is not None\n"
    )


def fixture_file(spec, entity, rows):
    label = f"{app_label(spec)}.{pascal(entity['name']).lower()}"
    records = []
    for index, row in enumerate(rows, start=1):
        row = dict(row)
        pk = row.pop("id", index)
        fields = {snake(key): value for key, value in row.items()}
        records.append({"model": label, "pk": pk, "fields": fields})
    return json.dumps(records, indent=2, ensure_ascii=False) + "\n"


def generate(spec):
    label = app_label(spec)
    files = [
        {"path": f"{label}/__init__.py", "content": ""},
        {
            "path": f"{label}/apps.py",
            "content": (
                "from django.apps import AppConfig\n\n\n"
                f"class {pascal(label)}Config(AppConfig):\n"
                '    default_auto_field = "django.db.models.BigAutoField"\n'
                f'    name = "{label}"\n'
            ),
        },
        {"path": f"{label}/models.py", "content": models_file(spec)},
    ]
    if spec["resources"]:
        files += [
            {"path": f"{label}/serializers.py", "content": serializers_file(spec)},
            {"path": f"{label}/views.py", "content": views_file(spec)},
            {"path": f"{label}/urls.py", "content": urls_file(spec)},
        ]
    if spec["roles"]:
        files.append({"path": f"{label}/permissions.py", "content": permissions_file(spec)})
    for seed in spec["seeds"]:
        entity = next((e for e in spec["entities"] if e["name"] == seed["entity"]), None)
        if entity and seed["rows"]:
            files.append({"path": f"{label}/fixtures/{snake(entity['name'])}.json", "content": fixture_file(spec, entity, seed["rows"])})
    return files
