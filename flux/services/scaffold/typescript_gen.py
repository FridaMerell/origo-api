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
        lines = [f"export type {pascal(entity['name'])} = {{", "  id: number;"]
        for field in entity["fields"]:
            ts_type = _TYPES[field["type"]]
            if field["nullable"] and ts_type != "unknown":
                ts_type += " | null"
            lines.append(f"  {api_name(field['name'], naming)}: {ts_type};")
        for relation in entity["relations"]:
            ts_type = "number[]" if relation["kind"] == "m2m" else "number"
            if relation["kind"] != "m2m" and (relation["nullable"] or relation["on_delete"] == "set_null"):
                ts_type += " | null"
            lines.append(f"  {api_name(relation['name'], naming)}: {ts_type};")
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def api_file(spec):
    names = sorted({pascal(resource["entity"]) for resource in spec["resources"]})
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
    for resource in spec["resources"]:
        name = pascal(resource["entity"])
        path, operations = resource["path"].strip("/"), resource["operations"]
        members = []
        if "list" in operations:
            members.append(f'  list: () => request<{name}[]>("/{path}/"),')
        if "retrieve" in operations:
            members.append(f'  retrieve: (id: number) => request<{name}>(`/{path}/${{id}}/`),')
        if "create" in operations:
            members.append(
                f'  create: (data: Omit<{name}, "id">) =>\n'
                f'    request<{name}>("/{path}/", {{ method: "POST", body: JSON.stringify(data) }}),'
            )
        if "update" in operations:
            members.append(
                f'  update: (id: number, data: Partial<Omit<{name}, "id">>) =>\n'
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
