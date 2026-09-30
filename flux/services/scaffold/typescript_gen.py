"""TypeScript target: type aliases, API client and route table."""

import json
import re

from .common import api_name, camel, pascal, snake

_TYPES = {
    "string": "string",
    "text": "string",
    "int": "number",
    "bigint": "number",
    "decimal": "number",
    "float": "number",
    "bool": "boolean",
    "date": "string",
    "datetime": "string",
    "time": "string",
    "uuid": "string",
    "json": "unknown",
    "email": "string",
    "url": "string",
}

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

_SCHEMA_TYPES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def _projection_type(schema, indent=""):
    """Translate the useful JSON Schema subset without guessing unknown shapes."""
    if not isinstance(schema, dict):
        return "unknown"
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        members = dict.fromkeys(
            _SCHEMA_TYPES[member] if member in _SCHEMA_TYPES else _projection_type({**schema, "type": member}, indent)
            for member in schema_type
        )
        return " | ".join(members) if members else "unknown"
    if schema_type in _SCHEMA_TYPES:
        return _SCHEMA_TYPES[schema_type]
    if schema_type == "array":
        return f"Array<{_projection_type(schema.get('items'))}>"
    if schema_type != "object" or not isinstance(schema.get("properties"), dict):
        return "unknown"
    # "required" is usually never filled in when a projection is captured from a real response;
    # treat every property as required unless the schema explicitly says otherwise (even `[]`).
    required = set(schema["required"]) if "required" in schema else set(schema["properties"])
    child_indent = indent + "  "
    properties = []
    for name, property_schema in schema["properties"].items():
        optional = "" if name in required else "?"
        key = name if _IDENTIFIER.match(name) else json.dumps(name)
        properties.append(
            f"{child_indent}{key}{optional}: {_projection_type(property_schema, child_indent)};"
        )
    return "{\n" + "\n".join(properties) + f"\n{indent}}}"


def types_file(spec):
    naming = spec["stack"]["api_naming"]
    blocks = []
    for entity in spec["entities"]:
        entity_name = pascal(entity["name"])
        lines = [f"export type {entity_name} = {{", "  id: number;"]
        for field in entity["fields"]:
            ts_type = _TYPES[field["type"]]
            if field["nullable"] and ts_type != "unknown":
                ts_type += " | null"
            lines.append(f"  {api_name(field['name'], naming)}: {ts_type};")
        for relation in entity["relations"]:
            target = pascal(relation["target"])
            ts_type = f'{target}["id"][]' if relation["kind"] == "m2m" else f'{target}["id"]'
            if relation["kind"] != "m2m" and relation["nullable"]:
                ts_type += " | null"
            lines.append(f"  {api_name(relation['name'], naming)}: {ts_type};")
        lines += [
            "}",
            "",
            f'export type {entity_name}Create = Omit<{entity_name}, "id">;',
            f"export type {entity_name}Update = Partial<{entity_name}Create>;",
        ]
        blocks.append("\n".join(lines))
    for resource in spec["resources"]:
        if not resource.get("filters"):
            continue
        entity_name = pascal(resource["entity"])
        filter_lines = [f"export type {entity_name}Filters = {{"]
        filter_lines.extend(f"  {name}?: string;" for name in resource.get("filters", []))
        filter_lines.append("}")
        blocks.append("\n".join(filter_lines))
    return "\n\n".join(blocks) + "\n"


def projections_file(spec):
    """Custom API response shapes that don't fit an entity: one plain, compile-time
    ``export type Name = {...}`` per projection (matching Opus's own hand-written dal types),
    kept in their own file, separate from the entity types, so they can be dropped into any project.
    """
    blocks = [
        f"export type {pascal(projection['name'])} = {_projection_type(projection['schema'])};"
        for projection in spec.get("api_projections", [])
    ]
    return "\n\n".join(blocks) + "\n"


def api_file(spec):
    """API access layer, matching the shape of Opus's ``_actions/actions.ts`` in origo-frontend:
    a plain ``request`` fetcher, ``cachedList``/``cachedRetrieve`` built on React's ``cache()``,
    and one flat exported ``xApi`` object per resource — no Context/providers.
    """
    resources = spec["resources"]
    type_names = {pascal(resource["entity"]) for resource in resources}
    for resource in resources:
        entity = pascal(resource["entity"])
        if resource.get("filters"):
            type_names.add(f"{entity}Filters")
        if "create" in resource["operations"]:
            type_names.add(f"{entity}Create")
        if "update" in resource["operations"]:
            type_names.add(f"{entity}Update")
    names = sorted(type_names)
    projection_names = {projection["name"] for projection in spec.get("api_projections", [])}
    used_projections = sorted(
        {
            _custom_operation_response_type(operation, projection_names)
            for operation in spec.get("api_operations", [])
            if operation.get("key") == "custom"
        }
        - {"unknown"}
    )
    auth = spec["stack"]["auth_method"]
    lines = [
        'import { cache } from "react";',
        f"import type {{ {', '.join(names)} }} from './types';",
        *([f"import type {{ {', '.join(used_projections)} }} from './api-projections';"] if used_projections else []),
        "",
        'let apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api";',
        "",
        "export function setApiBase(url: string) {",
        '  apiBase = url.replace(/[/]$/, "");',
        "}",
        "",
    ]
    if auth == "session":
        lines += [
            "function csrfToken(): string {",
            '  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);',
            '  return match ? decodeURIComponent(match[1]) : "";',
            "}",
            "",
        ]
        extra_headers = '    ...(init?.method && init.method !== "GET" ? { "X-CSRFToken": csrfToken() } : {}),'
    elif auth in ("token", "jwt"):
        scheme = "Token" if auth == "token" else "Bearer"
        lines += [
            "let authToken: string | null = null;",
            "",
            "export function setAuthToken(token: string | null) {",
            "  authToken = token;",
            "}",
            "",
        ]
        extra_headers = f'    ...(authToken ? {{ Authorization: `{scheme} ${{authToken}}` }} : {{}}),'
    else:
        extra_headers = None
    header_lines = ['    "Content-Type": "application/json",']
    if extra_headers:
        header_lines.append(extra_headers)
    lines += [
        "async function request<T>(path: string, init?: RequestInit): Promise<T> {",
        "  const response = await fetch(`${apiBase}${path}`, {",
        "    ...init,",
        "    headers: {",
        *header_lines,
        "      ...init?.headers,",
        "    },",
        '    credentials: "include",',
        "  });",
        "  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);",
        "  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);",
        "}",
    ]
    custom_operations = [op for op in spec.get("api_operations", []) if op.get("key") == "custom"]
    needs_cached_helpers = any(operation in resource["operations"] for resource in resources for operation in ("list", "retrieve"))
    needs_with_query = needs_cached_helpers or any(
        (op.get("method") or "GET").upper() == "GET" and any(p.get("in") != "path" for p in op.get("parameters", []))
        for op in custom_operations
    )
    if needs_with_query:
        lines += [
            "",
            "function withQuery(path: string, filters: Record<string, string | undefined>): string {",
            "  const params = new URLSearchParams();",
            "  for (const [key, value] of Object.entries(filters)) {",
            "    if (value !== undefined) params.set(key, value);",
            "  }",
            "  const query = params.toString();",
            "  return query ? `${path}?${query}` : path;",
            "}",
        ]
    if needs_cached_helpers:
        lines += [
            "",
            "function cachedList<T, Filters extends Record<string, string | undefined> = Record<string, string | undefined>>(",
            "  path: string,",
            ") {",
            "  const get = cache((query: string) => request<T[]>(query ? `${path}?${query}` : path));",
            '  return (filters?: Filters) => get(filters ? withQuery("", filters).slice(1) : "");',
            "}",
            "",
            "function cachedRetrieve<T>(path: string) {",
            "  return cache((id: number) => request<T>(`${path}${id}/`));",
            "}",
        ]
    for resource in resources:
        name = pascal(resource["entity"])
        path, operations = resource["path"].strip("/"), resource["operations"]
        members = []
        if "list" in operations:
            filters_type = f"{name}, {name}Filters" if resource.get("filters") else name
            members.append(f'  list: cachedList<{filters_type}>("/{path}/"),')
        if "retrieve" in operations:
            members.append(f'  retrieve: cachedRetrieve<{name}>("/{path}/"),')
        if "create" in operations:
            members.append(
                f'  create: (data: {name}Create) =>\n'
                f'    request<{name}>("/{path}/", {{ method: "POST", body: JSON.stringify(data) }}),'
            )
        if "update" in operations:
            members.append(
                f'  update: (id: number, data: {name}Update) =>\n'
                f'    request<{name}>(`/{path}/${{id}}/`, {{ method: "PATCH", body: JSON.stringify(data) }}),'
            )
        if "delete" in operations:
            members.append(f'  remove: (id: number) => request<void>(`/{path}/${{id}}/`, {{ method: "DELETE" }}),')
        lines += ["", f"export const {name[:1].lower() + name[1:]}Api = {{", *members, "};"]
    lines += _custom_operation_functions(spec)
    return "\n".join(lines) + "\n"


_PARAM_TYPES = {"integer": "number", "number": "number", "boolean": "boolean", "string": "string"}


def _param_name(parameter):
    return camel(parameter["name"])


def _custom_operation_response_type(operation, projection_names):
    """The type of a 2xx response: the linked projection if one exists, else ``unknown``."""
    candidates = [r for r in operation.get("responses", []) if 200 <= r["status_code"] < 300]
    for response in sorted(candidates, key=lambda r: r["status_code"]):
        if response["projection"] and response["projection"] in projection_names:
            return pascal(response["projection"])
    return "unknown"


def _custom_operation_path_expression(path, path_params):
    if not path_params:
        return json.dumps(path)
    expression = path
    for parameter in path_params:
        placeholder = "{" + parameter["name"] + "}"
        expression = expression.replace(placeholder, f"${{encodeURIComponent(String({_param_name(parameter)}))}}")
    return f"`{expression}`"


def _custom_operation_functions(spec):
    """One function per *custom* API operation (a path that doesn't fit the entity CRUD shape),
    matching how Opus itself calls a one-off route: a plain named function built on ``request<T>``,
    exactly like ``createWorkWithEditions`` in ``app/opus/_actions/actions.ts``.
    """
    operations = [op for op in spec.get("api_operations", []) if op.get("key") == "custom"]
    if not operations:
        return []
    projection_names = {projection["name"] for projection in spec.get("api_projections", [])}
    lines = []
    for operation in operations:
        lines.append("")
        name = camel(operation["title"]) if operation.get("title") else camel(f"{operation['key']}_{operation['resource']}")
        method = (operation.get("method") or "GET").upper()
        path_params = [p for p in operation.get("parameters", []) if p.get("in") == "path"]
        query_params = [p for p in operation.get("parameters", []) if p.get("in") != "path"]
        response_type = _custom_operation_response_type(operation, projection_names)
        args = [f"{_param_name(p)}: {_PARAM_TYPES.get(p.get('type'), 'string')}" for p in path_params]
        path_expression = _custom_operation_path_expression(operation["path"], path_params)
        init_parts = [f'method: "{method}"'] if method != "GET" else []
        if method not in ("GET", "HEAD") and operation.get("request_schema"):
            args.append(f"data: {_projection_type(operation['request_schema'])}")
            init_parts.append("body: JSON.stringify(data)")
        init = f", {{ {', '.join(init_parts)} }}" if init_parts else ""
        call = f"request<{response_type}>({path_expression}{init})"
        if query_params and method == "GET":
            filters_type = "Record<string, string | undefined>"
            args.append(f"params: {filters_type} = {{}}")
            call = f'request<{response_type}>(withQuery({path_expression}, params))'
        signature = ", ".join(args)
        if method == "GET":
            lines.append(f"export const {name} = cache(({signature}): Promise<{response_type}> => {call});")
        else:
            lines.append(f"export async function {name}({signature}): Promise<{response_type}> {{")
            lines.append(f"  return {call};")
            lines.append("}")
    return lines


def _plural(name):
    return name + "es" if name.endswith(("s", "x", "ch", "sh")) else name + "s"


def provider_files(spec):
    """Data providers matching Opus's ``_state/opus-context.tsx`` in origo-frontend: a context that
    holds already-fetched data (not the API functions), a ``<Name>DataProvider`` taking that data plus
    ``children`` as props, and one ``use<Entities>()`` selector hook per resource. The provider does not
    fetch anything itself; a server component fetches via ``api.ts`` and passes the data down as props.
    """
    resources_by_entity = {resource["entity"]: resource for resource in spec["resources"]}
    files = []
    for provider in spec.get("providers", []):
        selected = [resources_by_entity[name] for name in provider["resources"] if name in resources_by_entity]
        if not selected:
            continue
        name = pascal(provider["name"])
        fields = [(camel(_plural(resource["entity"])), pascal(resource["entity"])) for resource in selected]
        type_lines = "\n".join(f"  {field}: {entity}[];" for field, entity in fields)
        empty_lines = "\n".join(f"  {field}: [],".format(field=field) for field, _ in fields)
        hooks = "\n\n".join(
            f"export function use{pascal(_plural(resource['entity']))}() {{\n"
            f"  const {{ {camel(_plural(resource['entity']))} }} = useContext({name}Context);\n"
            f"  return {{ {camel(_plural(resource['entity']))} }};\n"
            "}"
            for resource in selected
        )
        source = (
            '"use client";\n\n'
            'import { createContext, useContext, type ReactNode } from "react";\n'
            f"import type {{ {', '.join(entity for _, entity in fields)} }} from \"../types\";\n\n"
            f"type {name}Data = {{\n{type_lines}\n}};\n\n"
            f"const EMPTY_DATA: {name}Data = {{\n{empty_lines}\n}};\n\n"
            f"const {name}Context = createContext<{name}Data>(EMPTY_DATA);\n\n"
            f"export function {name}DataProvider({{\n"
            "  children,\n"
            "  ...data\n"
            f"}}: {name}Data & {{ children: ReactNode }}) {{\n"
            f"  return <{name}Context.Provider value={{data}}>{{children}}</{name}Context.Provider>;\n"
            "}\n\n"
            f"{hooks}\n"
        )
        files.append({"path": f"providers/{snake(provider['name'])}-provider.tsx", "content": source})
    return files


def routes_file(spec):
    lines = ["export const routes = ["]
    for screen in spec["screens"]:
        entities = ", ".join(json.dumps(name) for name in screen["entities"])
        parent = json.dumps(screen["parent"]) if screen.get("parent") else "null"
        lines.append(
            f"  {{ name: {json.dumps(screen['name'])}, route: {json.dumps(screen['route'])}, "
            f"parent: {parent}, entities: [{entities}] }},"
        )
    lines += ["] as const;", ""]
    return "\n".join(lines)


def generate(spec):
    files = [{"path": "types.ts", "content": types_file(spec)}]
    if spec.get("api_projections"):
        files.append({"path": "api-projections.ts", "content": projections_file(spec)})
    if spec["resources"]:
        files.append({"path": "api.ts", "content": api_file(spec)})
        files.extend(provider_files(spec))
    if spec["screens"]:
        files.append({"path": "routes.ts", "content": routes_file(spec)})
    return files
