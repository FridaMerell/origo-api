"""Validation for inbound API integrations. Pure: no Django imports.

The design is checked against a real ``sample_response`` so a mapping can never point at a field the API
does not return, or at a value of the wrong type.
"""

import json
import keyword
import re

MAX_SAMPLE_CHARACTERS = 200_000
AUTH_TYPES = ["none", "api_key_header", "api_key_query", "bearer", "basic", "oauth_client"]
METHODS = ["GET", "POST"]
BODY_FORMATS = ["json", "form"]
PAGINATIONS = ["none", "offset", "page", "cursor"]
PARAM_LOCATIONS = ["query", "path", "body", "header"]
PARAM_TYPES = ["string", "int", "float", "bool"]
FILTER_OPS = ["eq", "ne", "in", "not_null", "is_null"]
RESERVED_ARGUMENTS = {"use_cache"}
SAMPLE_ITEMS_CHECKED = 20

_ENV = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
_WIRE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,99}$")
_HTTPS = re.compile(r"^https://[^\s\"'<>\\`{}]+$")
_PATH = re.compile(r"^/[^\s\"'<>\\`?#]*$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_JSON_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
_MISSING = object()


def py_name(name):
    """Python argument name for a wire parameter name (``pageSize`` -> ``page_size``)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value, label, *, maximum=300, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is required.")
    if len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters.")
    return value


def clean_env_name(value, label):
    value = _text(value, label, maximum=100)
    if value and not _ENV.match(value):
        raise ValueError(f"{label} must be an environment variable name like MY_SERVICE_KEY.")
    return value


def clean_base_url(value):
    value = _text(value, "base_url")
    if value and not _HTTPS.match(value):
        raise ValueError("base_url must be an https:// URL without spaces or quotes.")
    return value


def clean_auth(data):
    """Validate the auth settings of an integration; ``data`` holds the ``auth_*`` keys and ``oauth_token_url``."""
    auth_type = data.get("auth_type") or "none"
    if auth_type not in AUTH_TYPES:
        raise ValueError(f"auth_type must be one of: {', '.join(AUTH_TYPES)}.")
    cleaned = {
        "auth_type": auth_type,
        "auth_name": _text(data.get("auth_name"), "auth_name", maximum=100),
        "auth_env_var": clean_env_name(data.get("auth_env_var"), "auth_env_var"),
        "auth_secret_env_var": clean_env_name(data.get("auth_secret_env_var"), "auth_secret_env_var"),
        "oauth_token_url": _text(data.get("oauth_token_url"), "oauth_token_url"),
    }
    if cleaned["auth_name"] and not _WIRE.match(cleaned["auth_name"]):
        raise ValueError("auth_name must be a header or query parameter name.")
    if cleaned["oauth_token_url"] and not _HTTPS.match(cleaned["oauth_token_url"]):
        raise ValueError("oauth_token_url must be an https:// URL.")
    needs = {
        "none": [],
        "api_key_header": ["auth_name", "auth_env_var"],
        "api_key_query": ["auth_name", "auth_env_var"],
        "bearer": ["auth_env_var"],
        "basic": ["auth_env_var", "auth_secret_env_var"],
        "oauth_client": ["auth_env_var", "auth_secret_env_var", "oauth_token_url"],
    }[auth_type]
    for key in needs:
        if not cleaned[key]:
            raise ValueError(f"{key} is required for auth_type {auth_type}.")
    return cleaned


def resolve_path(data, path):
    """Follow a dotted path through dicts and list indexes. Returns ``(found, value)``."""
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def extract_items(payload, items_path):
    """The list of records in a response. A single object counts as one record."""
    if items_path:
        found, node = resolve_path(payload, items_path)
        if not found:
            raise ValueError(f"items_path {items_path!r} does not exist in the sample response.")
    else:
        node = payload
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return [node]
    raise ValueError("The response must be a list or an object at items_path.")


def _clean_path(value, label):
    value = _text(value, label, maximum=200)
    if value and not _JSON_PATH.match(value):
        raise ValueError(f"{label} must be a dotted path like data.items or 0.name.")
    return value


def clean_path(value):
    value = _text(value, "path", maximum=300, required=True)
    if not _PATH.match(value.replace("{", "").replace("}", "")):
        raise ValueError("path must start with / and contain no spaces, quotes, ? or #.")
    remainder = _PLACEHOLDER.sub("", value)
    if "{" in remainder or "}" in remainder:
        raise ValueError("path may only use {name} placeholders.")
    return value


def _default_matches(type_name, value):
    if value is None:
        return True
    return {
        "string": isinstance(value, str),
        "int": isinstance(value, int) and not isinstance(value, bool),
        "float": _is_number(value),
        "bool": isinstance(value, bool),
    }[type_name]


def clean_params(value, method, body_format, path):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("params must be a list of objects.")
    cleaned, seen = [], set()
    for item in value:
        name = _text(item.get("name"), "param.name", maximum=100, required=True)
        if not _WIRE.match(name):
            raise ValueError(f"param.name {name!r} is not a valid parameter name.")
        argument = py_name(name)
        if not argument or keyword.iskeyword(argument) or argument in RESERVED_ARGUMENTS or argument[0].isdigit():
            raise ValueError(f"param {name!r} cannot be used as a Python argument name.")
        if argument in seen:
            raise ValueError(f"Duplicate param name: {name}.")
        seen.add(argument)
        location = _text(item.get("in"), "param.in", maximum=10) or "query"
        if location not in PARAM_LOCATIONS:
            raise ValueError(f"param.in must be one of: {', '.join(PARAM_LOCATIONS)}.")
        if location == "body" and method != "POST":
            raise ValueError("Body parameters need method POST.")
        type_name = _text(item.get("type"), "param.type", maximum=10) or "string"
        if type_name not in PARAM_TYPES:
            raise ValueError(f"param.type must be one of: {', '.join(PARAM_TYPES)}.")
        required = item.get("required", location == "path")
        if not isinstance(required, bool):
            raise ValueError("param.required must be true or false.")
        default = item.get("default")
        if not _default_matches(type_name, default):
            raise ValueError(f"param {name!r} default does not match type {type_name}.")
        if location == "path":
            required = True
        if required and default is not None:
            raise ValueError(f"Required param {name!r} cannot have a default.")
        cleaned.append(
            {
                "name": name, "in": location, "type": type_name, "required": required,
                "default": default, "description": _text(item.get("description"), "param.description", maximum=200),
            }
        )
    placeholders = set(_PLACEHOLDER.findall(path))
    path_params = {item["name"] for item in cleaned if item["in"] == "path"}
    if placeholders != path_params:
        raise ValueError(
            f"Path placeholders {sorted(placeholders)} must match the path params {sorted(path_params)}."
        )
    return cleaned


def _positive_int(value, label, *, low=1, high=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer between {low} and {high}.")
    return value


def _wire_name(value, label):
    value = _text(value, label, maximum=100, required=True)
    if not _WIRE.match(value):
        raise ValueError(f"{label} must be a parameter name.")
    return value


def clean_pagination(pagination, config, params):
    if pagination not in PAGINATIONS:
        raise ValueError(f"pagination must be one of: {', '.join(PAGINATIONS)}.")
    if not isinstance(config, dict):
        raise ValueError("pagination_config must be an object.")
    if pagination == "none":
        return {}
    cleaned = {"max_pages": _positive_int(config.get("max_pages", 100), "pagination_config.max_pages", high=1000)}
    if pagination == "offset":
        cleaned["limit_param"] = _wire_name(config.get("limit_param"), "pagination_config.limit_param")
        cleaned["offset_param"] = _wire_name(config.get("offset_param"), "pagination_config.offset_param")
        cleaned["page_size"] = _positive_int(config.get("page_size"), "pagination_config.page_size", high=10000)
    elif pagination == "page":
        cleaned["page_param"] = _wire_name(config.get("page_param"), "pagination_config.page_param")
        cleaned["page_size"] = _positive_int(config.get("page_size"), "pagination_config.page_size", high=10000)
        cleaned["first_page"] = _positive_int(config.get("first_page", 1), "pagination_config.first_page", low=0, high=1)
        if config.get("size_param"):
            cleaned["size_param"] = _wire_name(config["size_param"], "pagination_config.size_param")
    else:
        cleaned["cursor_param"] = _wire_name(config.get("cursor_param"), "pagination_config.cursor_param")
        cleaned["next_cursor_path"] = _clean_path(config.get("next_cursor_path"), "pagination_config.next_cursor_path")
        if not cleaned["next_cursor_path"]:
            raise ValueError("pagination_config.next_cursor_path is required.")
        if config.get("size_param"):
            cleaned["size_param"] = _wire_name(config["size_param"], "pagination_config.size_param")
            cleaned["page_size"] = _positive_int(config.get("page_size"), "pagination_config.page_size", high=10000)
    paging_names = {value for key, value in cleaned.items() if key.endswith("_param")}
    clash = paging_names & {item["name"] for item in params}
    if clash:
        raise ValueError(f"Pagination parameters {sorted(clash)} are also declared as params.")
    return cleaned


def clean_filters(value):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("filters must be a list of objects.")
    cleaned = []
    for item in value:
        path = _clean_path(item.get("path"), "filter.path")
        if not path:
            raise ValueError("filter.path is required.")
        op = _text(item.get("op"), "filter.op", maximum=10) or "eq"
        if op not in FILTER_OPS:
            raise ValueError(f"filter.op must be one of: {', '.join(FILTER_OPS)}.")
        entry = {"path": path, "op": op}
        if op in ("eq", "ne"):
            operand = item.get("value")
            if not (operand is None or isinstance(operand, (str, bool)) or _is_number(operand)):
                raise ValueError("filter.value must be text, a number, a boolean or null.")
            entry["value"] = operand
        elif op == "in":
            operand = item.get("value")
            if not isinstance(operand, list) or not all(isinstance(v, (str, bool)) or _is_number(v) for v in operand):
                raise ValueError("filter.value must be a list of texts, numbers or booleans for op 'in'.")
            entry["value"] = operand
        cleaned.append(entry)
    return cleaned


def clean_mappings(value):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("mappings must be a list of objects.")
    cleaned, seen = [], set()
    for item in value:
        path = _clean_path(item.get("path"), "mapping.path")
        field = _text(item.get("field"), "mapping.field", maximum=100, required=True)
        if not path:
            raise ValueError("mapping.path is required.")
        if field in seen:
            raise ValueError(f"Field {field} is mapped more than once.")
        seen.add(field)
        cleaned.append({"path": path, "field": field})
    return cleaned


def _compatible(field_type, value, nullable):
    if value is None:
        return nullable
    if field_type in ("string", "text", "email", "url", "date", "datetime", "time", "uuid"):
        return isinstance(value, str)
    if field_type in ("int", "bigint"):
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type in ("decimal", "float"):
        return _is_number(value)
    if field_type == "bool":
        return isinstance(value, bool)
    return True


def _describe(value):
    return "null" if value is None else type(value).__name__


def _first_resolved(items, path):
    for item in items[:SAMPLE_ITEMS_CHECKED]:
        found, value = resolve_path(item, path)
        if found:
            return True, value
    return False, None


def clean_operation(data, entity=None):
    """Validate one operation. ``entity`` is ``{"fields": {name: {type, nullable}}, "relations": {name: kind}}`` or None."""
    name = _text(data.get("name"), "name", maximum=60, required=True)
    if not _IDENT.match(name) or keyword.iskeyword(name):
        raise ValueError("name must be a lowercase Python identifier like list_stations.")
    method = data.get("method") or "GET"
    if method not in METHODS:
        raise ValueError(f"method must be one of: {', '.join(METHODS)}.")
    body_format = data.get("body_format") or "json"
    if body_format not in BODY_FORMATS:
        raise ValueError(f"body_format must be one of: {', '.join(BODY_FORMATS)}.")
    path = clean_path(data.get("path"))
    params = clean_params(data.get("params", []), method, body_format, path)
    pagination = data.get("pagination") or "none"
    pagination_config = clean_pagination(pagination, data.get("pagination_config", {}), params)
    items_path = _clean_path(data.get("items_path"), "items_path")
    filters = clean_filters(data.get("filters", []))
    mappings = clean_mappings(data.get("mappings", []))
    key_field = _text(data.get("key_field"), "key_field", maximum=100)
    sync = data.get("sync", False)
    if not isinstance(sync, bool):
        raise ValueError("sync must be true or false.")
    interval = data.get("sync_interval_minutes")
    if interval is not None:
        interval = _positive_int(interval, "sync_interval_minutes", high=525600)
        if not sync:
            raise ValueError("sync_interval_minutes needs sync to be true.")
    ttl = data.get("cache_ttl_seconds")
    if ttl is not None:
        ttl = _positive_int(ttl, "cache_ttl_seconds", low=0, high=31536000)
    sample = data.get("sample_response")
    if sample is not None and len(json.dumps(sample)) > MAX_SAMPLE_CHARACTERS:
        raise ValueError("sample_response is larger than 200 kB; keep a representative excerpt of the real response.")

    if mappings and entity is None:
        raise ValueError("mappings need an entity to map onto.")
    if sync:
        if entity is None:
            raise ValueError("sync needs an entity.")
        if not mappings or not key_field:
            raise ValueError("sync needs mappings and a key_field.")
    if key_field and key_field not in {mapping["field"] for mapping in mappings}:
        raise ValueError(f"key_field {key_field!r} must be one of the mapped fields.")
    if entity is not None:
        for mapping in mappings:
            field = mapping["field"]
            kind = entity["relations"].get(field)
            if field not in entity["fields"] and kind is None:
                raise ValueError(f"Mapped field {field!r} is not a field or relation of the entity.")
            if kind == "m2m":
                raise ValueError(f"Many-to-many relation {field!r} cannot be mapped.")
        if key_field and key_field not in entity["fields"]:
            raise ValueError(f"key_field {key_field!r} must be a plain field of the entity, not a relation.")

    if mappings and sample is None:
        raise ValueError("sample_response is required: capture a real response from the live API before mapping it.")
    if sample is not None:
        items = extract_items(sample, items_path)
        if pagination != "none" and not isinstance(resolve_path(sample, items_path)[1] if items_path else sample, list):
            raise ValueError("A paginated operation needs a list at items_path in the sample response.")
        if (mappings or filters) and not items:
            raise ValueError("The sample response contains no items to verify the mappings and filters against.")
        for entry in filters:
            if not _first_resolved(items, entry["path"])[0]:
                raise ValueError(f"filter path {entry['path']!r} does not exist in the sample response.")
        for mapping in mappings:
            found, value = _first_resolved(items, mapping["path"])
            if not found:
                raise ValueError(f"mapping path {mapping['path']!r} does not exist in the sample response.")
            spec = entity["fields"].get(mapping["field"])
            if spec is None:
                if not (value is None or (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, str)):
                    raise ValueError(f"Relation {mapping['field']!r} must map to a primary key value, got {_describe(value)}.")
            elif not _compatible(spec["type"], value, spec["nullable"]):
                raise ValueError(
                    f"mapping path {mapping['path']!r} gives {_describe(value)} "
                    f"but field {mapping['field']!r} is {spec['type']}."
                )

    return {
        "name": name, "method": method, "path": path, "body_format": body_format, "params": params,
        "items_path": items_path, "pagination": pagination, "pagination_config": pagination_config,
        "filters": filters, "mappings": mappings, "key_field": key_field, "sync": sync,
        "sync_interval_minutes": interval, "cache_ttl_seconds": ttl, "sample_response": sample,
    }
