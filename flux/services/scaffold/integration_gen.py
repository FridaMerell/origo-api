"""Integration target: a Django client, sync, tasks, tests and docs for each inbound data API."""

import json
import re

from .common import app_label, pascal, snake
from .integration import py_name, resolve_path

_ANNOTATIONS = {"string": "str", "int": "int", "float": "float", "bool": "bool"}
_EXAMPLES = {"string": "example", "int": 1, "float": 1.0, "bool": True}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_RUNTIME = '''
_MISSING = object()
_last_request_at = 0.0
_oauth_state = {"token": None, "expires_at": 0.0}


class __P__Error(Exception):
    """Base class for errors from this integration."""


class __P__ConfigurationError(__P__Error):
    """A required environment variable is not set."""


class __P__APIError(__P__Error):
    """The upstream API failed or returned something unexpected."""


def _env(name):
    value = os.environ.get(name)
    if not value:
        raise __P__ConfigurationError(f"{name} is not set.")
    return value


def _oauth_token():
    now = time.time()
    if _oauth_state["token"] and _oauth_state["expires_at"] > now + 30:
        return _oauth_state["token"]
    data = {
        "grant_type": "client_credentials",
        "client_id": _env(AUTH_ENV_VAR),
        "client_secret": _env(AUTH_SECRET_ENV_VAR),
    }
    try:
        response = requests.post(OAUTH_TOKEN_URL, data=data, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise __P__APIError(f"Could not obtain an OAuth token: {exc}") from exc
    _oauth_state["token"] = token
    _oauth_state["expires_at"] = now + float(payload.get("expires_in", 300))
    return token


def _apply_auth(headers, query):
    """Add credentials to a request. Returns the ``auth`` argument for requests."""
    if AUTH_TYPE == "api_key_header":
        headers[AUTH_NAME] = _env(AUTH_ENV_VAR)
    elif AUTH_TYPE == "api_key_query":
        query[AUTH_NAME] = _env(AUTH_ENV_VAR)
    elif AUTH_TYPE == "bearer":
        headers["Authorization"] = f"Bearer {_env(AUTH_ENV_VAR)}"
    elif AUTH_TYPE == "oauth_client":
        headers["Authorization"] = f"Bearer {_oauth_token()}"
    elif AUTH_TYPE == "basic":
        return (_env(AUTH_ENV_VAR), _env(AUTH_SECRET_ENV_VAR))
    return None


def _throttle():
    global _last_request_at
    if RATE_LIMIT_PER_MINUTE:
        wait = _last_request_at + 60.0 / RATE_LIMIT_PER_MINUTE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    _last_request_at = time.monotonic()


def _retry_after(response):
    try:
        return min(float(response.headers.get("Retry-After", "")), 30.0)
    except (TypeError, ValueError):
        return None


def _request(method, path, *, params=None, body=None, form=None, headers=None):
    url = BASE_URL.rstrip("/") + path
    headers = dict(headers or {})
    query = {key: value for key, value in (params or {}).items() if value is not None}
    auth = _apply_auth(headers, query)
    last_error = None
    for attempt in range(RETRIES + 1):
        delay = None
        _throttle()
        try:
            response = requests.request(
                method, url, params=query, json=body, data=form, headers=headers, auth=auth, timeout=TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            status = response.status_code
            if status == 429 or status >= 500:
                last_error = __P__APIError(f"HTTP {status} from {url}")
                delay = _retry_after(response)
            elif status >= 400:
                raise __P__APIError(f"HTTP {status} from {url}: {response.text[:200]}")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise __P__APIError(f"{url} did not return JSON.") from exc
        if attempt < RETRIES:
            time.sleep(delay if delay is not None else min(2 ** attempt, 10))
    raise __P__APIError(f"{url} failed after {RETRIES + 1} attempts: {last_error}") from last_error


def _resolve(data, path):
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _items(payload, items_path):
    node = _resolve(payload, items_path) if items_path else payload
    if node is _MISSING:
        raise __P__APIError(f"The response has no {items_path!r}; the API may have changed.")
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return [node]
    raise __P__APIError("Unexpected response shape.")


def _passes(item, filters):
    for entry in filters:
        value = _resolve(item, entry["path"])
        present = value is not _MISSING
        op = entry["op"]
        if op == "eq" and not (present and value == entry["value"]):
            return False
        if op == "ne" and present and value == entry["value"]:
            return False
        if op == "in" and not (present and value in entry["value"]):
            return False
        if op == "not_null" and (not present or value is None):
            return False
        if op == "is_null" and present and value is not None:
            return False
    return True


def _cached(name, arguments, ttl, use_cache, fetch):
    if not use_cache or not ttl:
        return fetch()
    digest = hashlib.sha256(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()
    key = f"__SLUG__:{name}:{digest}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    result = fetch()
    cache.set(key, result, ttl)
    return result
'''


def _doc(text):
    return text.replace("\\", "\\\\").replace('"""', "'''").strip()


def _path_expression(path):
    if not _PLACEHOLDER.search(path):
        return repr(path)
    return 'f"' + _PLACEHOLDER.sub(lambda m: "{quote(str(" + py_name(m.group(1)) + "), safe='')}", path) + '"'


def _dict_expression(entries):
    return "{" + ", ".join(f"{wire!r}: {argument}" for wire, argument in entries) + "}"


def _kwarg(spec, field):
    """The model keyword a mapped field is stored under (relations use ``<name>_id``)."""
    entity = next((e for e in spec["entities"] if e["name"] == field["entity"]), None)
    is_relation = entity is not None and any(r["name"] == field["field"] and r["kind"] != "m2m" for r in entity["relations"])
    return snake(field["field"]) + ("_id" if is_relation else "")


def _fetch_lines(op):
    request = f"_request({op['method']!r}, path, params={{params}}, body=body, form=form, headers=headers)"
    config = op["pagination_config"]
    filters, items_path = repr(op["filters"]), repr(op["items_path"])
    finish = f"        return [item for item in items if _passes(item, {filters})]"
    if op["pagination"] == "none":
        return [
            f"        payload = {request.format(params='query')}",
            f"        return [item for item in _items(payload, {items_path}) if _passes(item, {filters})]",
        ]
    error = (
        f'            raise __P__APIError("More than {config["max_pages"]} pages; '
        'narrow the query or raise the page limit.")'
    )
    lines = ["        items = []"]
    if op["pagination"] == "offset":
        size = config["page_size"]
        lines += [
            "        offset = 0",
            f"        for _ in range({config['max_pages']}):",
            f"            page_query = {{**query, {config['limit_param']!r}: {size}, {config['offset_param']!r}: offset}}",
            f"            page = _items({request.format(params='page_query')}, {items_path})",
            "            items.extend(page)",
            f"            if len(page) < {size}:",
            "                break",
            f"            offset += {size}",
            "        else:",
            error,
        ]
    elif op["pagination"] == "page":
        size = config["page_size"]
        size_entry = f", {config['size_param']!r}: {size}" if config.get("size_param") else ""
        lines += [
            f"        number = {config['first_page']}",
            f"        for _ in range({config['max_pages']}):",
            f"            page_query = {{**query, {config['page_param']!r}: number{size_entry}}}",
            f"            page = _items({request.format(params='page_query')}, {items_path})",
            "            items.extend(page)",
            f"            if len(page) < {size}:",
            "                break",
            "            number += 1",
            "        else:",
            error,
        ]
    else:
        lines += [
            "        cursor = None",
            f"        for _ in range({config['max_pages']}):",
            "            page_query = dict(query)",
            "            if cursor is not None:",
            f"                page_query[{config['cursor_param']!r}] = cursor",
        ]
        if config.get("size_param"):
            lines.append(f"            page_query[{config['size_param']!r}] = {config['page_size']}")
        lines += [
            f"            payload = {request.format(params='page_query')}",
            f"            items.extend(_items(payload, {items_path}))",
            f"            cursor = _resolve(payload, {config['next_cursor_path']!r})",
            '            if cursor is _MISSING or cursor in (None, ""):',
            "                break",
            "        else:",
            error,
        ]
    lines.append(finish)
    return lines


def _operation_source(op, default_ttl):
    required, optional, query, body, form, headers, arguments = [], [], [], [], [], [], []
    for param in op["params"]:
        name, annotation = py_name(param["name"]), _ANNOTATIONS[param["type"]]
        if param["required"]:
            required.append(f"{name}: {annotation}")
        elif param["default"] is None:
            optional.append(f"{name}: {annotation} | None = None")
        else:
            optional.append(f"{name}: {annotation} = {param['default']!r}")
        arguments.append((name, name))
        target = {"query": query, "path": [], "body": form if op["body_format"] == "form" else body, "header": headers}[param["in"]]
        target.append((param["name"], name))
    signature = ", ".join(["*", *required, *optional, "use_cache: bool = True"])
    ttl = default_ttl if op["cache_ttl_seconds"] is None else op["cache_ttl_seconds"]
    description = _doc(op["description"] or op["name"].replace("_", " ").capitalize())
    lines = [
        f"def {op['name']}({signature}) -> list[dict[str, Any]]:",
        f'    """{description}',
        "",
        f"    {op['method']} {op['path']}",
        '    """',
        f"    path = {_path_expression(op['path'])}",
        f"    query = {_dict_expression(query)}",
    ]
    for label, entries in (("body", body), ("form", form)):
        if entries:
            lines.append(f"    {label} = {{k: v for k, v in {_dict_expression(entries)}.items() if v is not None}}")
        else:
            lines.append(f"    {label} = None")
    lines += [
        f"    headers = {_dict_expression(headers)}",
        "",
        "    def _fetch():",
        *_fetch_lines(op),
        "",
        f"    return _cached({op['name']!r}, {_dict_expression(arguments)}, {ttl}, use_cache, _fetch)",
    ]
    return "\n".join(lines)


def _mapping_source(spec, integration, op):
    entries = {_kwarg(spec, {"entity": op["entity"], "field": m["field"]}): m["path"] for m in op["mappings"]}
    constant = f"{op['name'].upper()}_MAPPING"
    return "\n".join(
        [
            f"{constant} = {json.dumps(entries, indent=4)}",
            "",
            "",
            f"def map_{op['name']}(item: dict[str, Any]) -> dict[str, Any]:",
            f'    """Model field values for one record returned by {op["name"]}()."""',
            "    values = {}",
            f"    for field, path in {constant}.items():",
            "        value = _resolve(item, path)",
            "        values[field] = None if value is _MISSING else value",
            "    return values",
        ]
    )


def _client_source(spec, integration):
    prefix, slug = pascal(integration["name"]), snake(integration["name"])
    header = [
        f'"""Client for {_doc(integration["name"])}.',
        "",
        "Generated by Flux from the integration design. Each operation was designed against a real sample",
        "response; verify the live API again before relying on a new one.",
        '"""',
        "",
        "import hashlib",
        "import json",
        "import os",
        "import time",
        "from typing import Any",
        "from urllib.parse import quote",
        "",
        "import requests",
        "from django.core.cache import cache",
        "",
        f"BASE_URL = {integration['base_url']!r}",
        f"TIMEOUT_SECONDS = {integration['timeout_seconds']}",
        f"RETRIES = {integration['retries']}",
        f"RATE_LIMIT_PER_MINUTE = {integration['rate_limit_per_minute']!r}",
        f"AUTH_TYPE = {integration['auth_type']!r}",
        f"AUTH_NAME = {integration['auth_name']!r}",
        f"AUTH_ENV_VAR = {integration['auth_env_var']!r}",
        f"AUTH_SECRET_ENV_VAR = {integration['auth_secret_env_var']!r}",
        f"OAUTH_TOKEN_URL = {integration['oauth_token_url']!r}",
    ]
    parts = ["\n".join(header), _RUNTIME.replace("__SLUG__", slug).strip("\n")]
    for op in integration["operations"]:
        parts.append(_operation_source(op, integration["cache_ttl_seconds"]))
        if op["mappings"]:
            parts.append(_mapping_source(spec, integration, op))
    return "\n\n\n".join(parts).replace("__P__", prefix) + "\n"


def _required_fields(spec, op):
    entity = next((e for e in spec["entities"] if e["name"] == op["entity"]), None)
    if entity is None:
        raise ValueError(f"Operation {op['name']} maps onto an entity that no longer exists.")
    fields = {f["name"]: f for f in entity["fields"]}
    relations = {r["name"]: r for r in entity["relations"]}
    required = []
    for mapping in op["mappings"]:
        name = mapping["field"]
        if name not in fields and name not in relations:
            raise ValueError(f"Operation {op['name']} maps {name!r}, which is no longer a field of {entity['name']}.")
        if name == op["key_field"]:
            continue
        nullable = fields[name]["nullable"] if name in fields else (relations[name]["nullable"] or relations[name]["on_delete"] == "set_null")
        if not nullable:
            required.append(_kwarg(spec, {"entity": op["entity"], "field": name}))
    return required


def _sync_ops(integration):
    return [op for op in integration["operations"] if op["sync"]]


def _sync_source(spec, integration):
    slug, label = snake(integration["name"]), app_label(spec)
    ops = _sync_ops(integration)
    models = sorted({pascal(op["entity"]) for op in ops})
    lines = [
        f'"""Sync {_doc(integration["name"])} into the database. Generated by Flux."""',
        "",
        "import logging",
        "",
        "from django.db import transaction",
        "",
        f"from ..models import {', '.join(models)}",
        f"from . import {slug} as client",
        "",
        "logger = logging.getLogger(__name__)",
    ]
    for op in ops:
        model, key = pascal(op["entity"]), snake(op["key_field"])
        lines += [
            "",
            "",
            f"def sync_{op['name']}(**params) -> dict[str, int]:",
            f'    """Fetch {op["name"]} fresh (bypassing the cache) and upsert one {model} per record, keyed by {key}."""',
            f"    items = client.{op['name']}(use_cache=False, **params)",
            "    created = updated = skipped = 0",
            "    with transaction.atomic():",
            "        for item in items:",
            f"            values = client.map_{op['name']}(item)",
            f'            key = values.pop("{key}", None)',
            f'            if key in (None, "") or any(values.get(field) is None for field in {_required_fields(spec, op)!r}):',
            "                skipped += 1",
            "                continue",
            f"            _, was_created = {model}.objects.update_or_create({key}=key, defaults=values)",
            "            created += was_created",
            "            updated += not was_created",
            f'    logger.info("sync_{op["name"]}: %d created, %d updated, %d skipped", created, updated, skipped)',
            '    return {"created": created, "updated": updated, "skipped": skipped}',
        ]
    return "\n".join(lines) + "\n"


def _tasks_source(spec, entries):
    lines = [
        '"""Background sync tasks for inbound API integrations. Generated by Flux."""',
        "",
        "import logging",
        "from datetime import timedelta",
        "",
        "from django.utils import timezone",
        "from django_tasks import task",
        "",
        "logger = logging.getLogger(__name__)",
    ]
    for integration, op in entries:
        slug, function = snake(integration["name"]), f"run_sync_{snake(integration['name'])}_{op['name']}"
        lines += [
            "",
            "",
            "@task()",
            f"def {function}(**params):",
            f'    """Sync {op["name"]} from {_doc(integration["name"])} and schedule the next run."""',
            f"    from .integrations import {slug}_sync",
            "",
            f"    result = {slug}_sync.sync_{op['name']}(**params)",
            f'    logger.info("{function}: %s", result)',
            f"    {function}.using(run_after=timezone.now() + timedelta(minutes={op['sync_interval_minutes']})).enqueue(**params)",
            "    return result",
        ]
    return "\n".join(lines) + "\n"


def _command_source(spec, integration):
    slug = snake(integration["name"])
    entries = []
    for op in _sync_ops(integration):
        declared = {py_name(p["name"]): (p["type"], p["required"]) for p in op["params"]}
        entries.append(f"    {op['name']!r}: ({slug}_sync.sync_{op['name']}, {declared!r}),")
    return "\n".join(
        [
            f'"""Sync {_doc(integration["name"])} into the database. Generated by Flux."""',
            "",
            "from django.core.management.base import BaseCommand, CommandError",
            "",
            f"from ...integrations import {slug}_sync",
            "",
            "OPERATIONS = {",
            *entries,
            "}",
            "CASTS = {",
            '    "string": str,',
            '    "int": int,',
            '    "float": float,',
            '    "bool": lambda value: value.lower() in ("1", "true", "yes"),',
            "}",
            "",
            "",
            "class Command(BaseCommand):",
            f'    help = "Sync {_doc(integration["name"])} into the database."',
            "",
            "    def add_arguments(self, parser):",
            '        parser.add_argument("--operation", action="append", choices=sorted(OPERATIONS),',
            '                            help="Operation to run; repeat for several (default: all).")',
            '        parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",',
            '                            help="Parameter for the operations that declare it (Python argument name).")',
            "",
            "    def handle(self, *args, **options):",
            "        raw = {}",
            '        for entry in options["param"]:',
            '            name, separator, value = entry.partition("=")',
            "            if not separator:",
            '                raise CommandError(f"--param expects NAME=VALUE, got {entry!r}.")',
            "            raw[name] = value",
            '        for name in options["operation"] or sorted(OPERATIONS):',
            "            function, declared = OPERATIONS[name]",
            "            params = {}",
            "            for argument, (type_name, required) in declared.items():",
            "                if argument in raw:",
            "                    try:",
            "                        params[argument] = CASTS[type_name](raw[argument])",
            "                    except ValueError as exc:",
            '                        raise CommandError(f"{argument} must be {type_name}: {exc}") from exc',
            "                elif required:",
            '                    raise CommandError(f"{name} needs --param {argument}=...")',
            "            self.stdout.write(f\"{name}: {function(**params)}\")",
        ]
    ) + "\n"


def _apply_filters(items, filters):
    def passes(item):
        for entry in filters:
            found, value = resolve_path(item, entry["path"])
            op = entry["op"]
            if op == "eq" and not (found and value == entry["value"]):
                return False
            if op == "ne" and found and value == entry["value"]:
                return False
            if op == "in" and not (found and value in entry["value"]):
                return False
            if op == "not_null" and (not found or value is None):
                return False
            if op == "is_null" and found and value is not None:
                return False
        return True

    return [item for item in items if passes(item)]


def _sample_items(op):
    sample = op["sample_response"]
    if sample is None:
        return None
    found, node = resolve_path(sample, op["items_path"]) if op["items_path"] else (True, sample)
    if not found:
        return None
    return node if isinstance(node, list) else [node]


def _test_arguments(op):
    values = {py_name(p["name"]): _EXAMPLES[p["type"]] for p in op["params"] if p["required"]}
    return ", ".join(["use_cache=False", *(f"{name}={value!r}" for name, value in values.items())])


def _fetchable(op, items):
    """Whether one mocked response is enough for the operation to finish."""
    if op["pagination"] == "none":
        return True
    config = op["pagination_config"]
    if op["pagination"] == "cursor":
        found, cursor = resolve_path(op["sample_response"], config["next_cursor_path"])
        return not found or cursor in (None, "")
    return len(items) < config["page_size"]


def _tests_source(spec, integration):
    slug, prefix, label = snake(integration["name"]), pascal(integration["name"]), app_label(spec)
    env = {name: "test" for name in (integration["auth_env_var"], integration["auth_secret_env_var"]) if name}
    lines = [
        f'"""Tests for the {_doc(integration["name"])} client. Generated by Flux from real sample responses."""',
        "",
        "import json",
        "import os",
        "from pathlib import Path",
        "from unittest import mock",
        "",
        "from django.test import SimpleTestCase",
        "",
        f"from {label}.integrations import {slug} as client",
        "",
        'FIXTURES = Path(__file__).parent / "fixtures"',
        f"ENV = {env!r}",
        "",
        "",
        "def load(name):",
        '    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))',
        "",
        "",
        "def response(payload, status=200):",
        "    result = mock.Mock()",
        "    result.status_code = status",
        "    result.headers = {}",
        '    result.text = ""',
        "    result.json.return_value = payload",
        "    return result",
    ]
    first_arguments = None
    for op in integration["operations"]:
        items = _sample_items(op)
        arguments = _test_arguments(op)
        first_arguments = first_arguments or (op["name"], arguments)
        if items is None:
            continue
        kept = _apply_filters(items, op["filters"])
        lines += [
            "",
            "",
            f"class {pascal(op['name'])}Tests(SimpleTestCase):",
            f'    sample = load("{slug}_{op["name"]}.json")',
        ]
        if _fetchable(op, items):
            lines += [
                "",
                "    def test_returns_the_filtered_records(self):",
                "        with mock.patch.dict(os.environ, ENV), mock.patch.object(",
                '            client.requests, "request", return_value=response(self.sample)',
                "        ) as request:",
                f"            items = client.{op['name']}({arguments})",
                f"        self.assertEqual(len(items), {len(kept)})",
                "        self.assertEqual(request.call_count, 1)",
            ]
        else:
            lines += [
                "",
                "    def test_filters_keep_the_expected_records(self):",
                f"        items = client._items(self.sample, {op['items_path']!r})",
                f"        kept = [item for item in items if client._passes(item, {op['filters']!r})]",
                f"        self.assertEqual(len(kept), {len(kept)})",
            ]
        if op["mappings"] and kept:
            expected = {}
            for mapping in op["mappings"]:
                found, value = resolve_path(kept[0], mapping["path"])
                expected[_kwarg(spec, {"entity": op["entity"], "field": mapping["field"]})] = value if found else None
            lines += [
                "",
                "    def test_maps_the_first_kept_record(self):",
                f"        items = client._items(self.sample, {op['items_path']!r})",
                f"        kept = [item for item in items if client._passes(item, {op['filters']!r})]",
                f"        self.assertEqual(client.map_{op['name']}(kept[0]), {expected!r})",
            ]
    name, arguments = first_arguments
    lines += ["", "", f"class {prefix}RuntimeTests(SimpleTestCase):"]
    if integration["auth_type"] != "none":
        lines += [
            "    def test_missing_credentials_fail_before_any_request(self):",
            '        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(client.requests, "request") as request:',
            f"            with self.assertRaises(client.{prefix}ConfigurationError):",
            f"                client.{name}({arguments})",
            "        request.assert_not_called()",
            "",
        ]
    lines += [
        "    def test_upstream_errors_are_retried_and_reported(self):",
        "        with mock.patch.dict(os.environ, ENV), mock.patch.object(client.time, \"sleep\"), mock.patch.object(",
        '            client.requests, "request", return_value=response({}, status=503)',
        "        ) as request:",
        f"            with self.assertRaises(client.{prefix}APIError):",
        f"                client.{name}({arguments})",
        "        self.assertEqual(request.call_count, client.RETRIES + 1)",
        "",
        "    def test_client_errors_are_not_retried(self):",
        "        with mock.patch.dict(os.environ, ENV), mock.patch.object(",
        '            client.requests, "request", return_value=response({}, status=404)',
        "        ) as request:",
        f"            with self.assertRaises(client.{prefix}APIError):",
        f"                client.{name}({arguments})",
        "        self.assertEqual(request.call_count, 1)",
    ]
    return "\n".join(lines) + "\n"


def _docs_source(spec, integration):
    slug, label = snake(integration["name"]), app_label(spec)
    env = [name for name in (integration["auth_env_var"], integration["auth_secret_env_var"], *integration["env_vars"]) if name]
    lines = [f"# {integration['name']}", ""]
    if integration["description"]:
        lines += [integration["description"], ""]
    lines += [
        "Generated by Flux from the integration design. The client lives in "
        f"`{label}/integrations/{slug}.py`.",
        "",
        "## Connection",
        "",
        f"- Base URL: `{integration['base_url']}`",
        f"- Auth: `{integration['auth_type']}`" + (f" (`{integration['auth_name']}`)" if integration["auth_name"] else ""),
        f"- Timeout {integration['timeout_seconds']} s, {integration['retries']} retries, "
        f"rate limit {integration['rate_limit_per_minute'] or 'none'} per minute, "
        f"default cache {integration['cache_ttl_seconds']} s",
    ]
    if env:
        lines += ["", "Environment variables (already in `.env.example`):", ""]
        lines += [f"- `{name}`" for name in dict.fromkeys(env)]
    lines += ["", "## Operations", "", "| Function | Request | Parameters | Paging | Maps to | Synced |", "|---|---|---|---|---|---|"]
    for op in integration["operations"]:
        params = ", ".join(f"`{py_name(p['name'])}`" + ("" if p["required"] else "?") for p in op["params"]) or "-"
        target = f"`{op['entity']}`" if op["entity"] else "-"
        synced = f"every {op['sync_interval_minutes']} min" if op["sync"] and op["sync_interval_minutes"] else ("manual" if op["sync"] else "-")
        lines.append(f"| `{op['name']}()` | {op['method']} `{op['path']}` | {params} | {op['pagination']} | {target} | {synced} |")
    for op in integration["operations"]:
        if op["mappings"]:
            lines += ["", f"### `{op['name']}` mapping", "", "| Response path | Field |", "|---|---|"]
            lines += [f"| `{m['path']}` | `{m['field']}` |" for m in op["mappings"]]
            if op["key_field"]:
                lines += ["", f"Records are matched on `{op['key_field']}`."]
            if op["filters"]:
                lines += ["", "Only records matching " + ", ".join(f"`{f['path']} {f['op']}`" for f in op["filters"]) + " are kept."]
    lines += [
        "",
        "## Using it",
        "",
        "On demand (cached; pass `use_cache=False` to bypass):",
        "",
        "```python",
        f"from {label}.integrations import {slug}",
        "",
        f"records = {slug}.{integration['operations'][0]['name']}()",
        "```",
    ]
    if _sync_ops(integration):
        lines += [
            "",
            "Scheduled sync into the models:",
            "",
            "```bash",
            f"python manage.py sync_{slug} --param name=value",
            "```",
            "",
            "Operations with a sync interval also have a `django_tasks` task in `tasks.py` that re-queues itself.",
        ]
    lines += [
        "",
        "## Verify before you trust",
        "",
        "- The operations were designed against the sample responses stored in Flux. Re-run one against the live API",
        "  after any change to the upstream service, and update the sample if the shape changed.",
        "- Only JSON responses are supported. For XML, WKT geometry, OGC APIs or unusual paging, start from this",
        "  client and adapt it by hand.",
        "- Convert geometry to GeoJSON (WGS 84, `[lon, lat]`) before storing it.",
        "- Decide deliberately which fields to keep; do not store everything the API returns.",
        "",
    ]
    return "\n".join(lines)


def generate(spec):
    label = app_label(spec)
    integrations = [i for i in spec["integrations"] if i.get("operations")]
    if not integrations:
        raise ValueError("No integration has operations: add an operation to an inbound API integration first.")
    files = [
        {"path": f"{label}/integrations/__init__.py", "content": ""},
    ]
    task_entries = []
    has_sync = False
    for integration in integrations:
        slug = snake(integration["name"])
        if not integration["base_url"]:
            raise ValueError(f"Integration {integration['name']} needs a base_url.")
        files.append({"path": f"{label}/integrations/{slug}.py", "content": _client_source(spec, integration)})
        if _sync_ops(integration):
            has_sync = True
            files.append({"path": f"{label}/integrations/{slug}_sync.py", "content": _sync_source(spec, integration)})
            files.append({"path": f"{label}/management/commands/sync_{slug}.py", "content": _command_source(spec, integration)})
            task_entries += [(integration, op) for op in _sync_ops(integration) if op["sync_interval_minutes"]]
        files.append({"path": f"{label}/tests/test_{slug}.py", "content": _tests_source(spec, integration)})
        for op in integration["operations"]:
            if op["sample_response"] is not None:
                files.append(
                    {
                        "path": f"{label}/tests/fixtures/{slug}_{op['name']}.json",
                        "content": json.dumps(op["sample_response"], indent=2, ensure_ascii=False) + "\n",
                    }
                )
        files.append({"path": f"docs/integrations/{slug}.md", "content": _docs_source(spec, integration)})
    files.append({"path": f"{label}/tests/__init__.py", "content": ""})
    if has_sync:
        files += [
            {"path": f"{label}/management/__init__.py", "content": ""},
            {"path": f"{label}/management/commands/__init__.py", "content": ""},
        ]
    if task_entries:
        files.append({"path": f"{label}/tasks.py", "content": _tasks_source(spec, task_entries)})
    return files
