"""TypeScript target: type aliases, API client and route table."""

import json

from .common import api_name, pascal

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


def api_file(spec):
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
    auth = spec["stack"]["auth_method"]
    lines = [
        f"import type {{ {', '.join(names)} }} from './types';",
        "",
        'const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";',
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
        "  const response = await fetch(`${API_BASE}${path}`, {",
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
    if any(resource.get("filters") for resource in resources):
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
    for resource in resources:
        name = pascal(resource["entity"])
        path, operations = resource["path"].strip("/"), resource["operations"]
        members = []
        if "list" in operations:
            if resource.get("filters"):
                members.append(
                    f'  list: (filters: {name}Filters = {{}}) =>\n'
                    f'    request<{name}[]>(withQuery("/{path}/", filters)),'
                )
            else:
                members.append(f'  list: () => request<{name}[]>("/{path}/"),')
        if "retrieve" in operations:
            members.append(f'  retrieve: (id: number) => request<{name}>(`/{path}/${{id}}/`),')
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
    return "\n".join(lines) + "\n"


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
    if spec["resources"]:
        files.append({"path": "api.ts", "content": api_file(spec)})
    if spec["screens"]:
        files.append({"path": "routes.ts", "content": routes_file(spec)})
    return files
