"""Naming helpers shared by the scaffold generators."""

import json
import re

_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+\d*|[A-Z]+\d*|\d+")


def words(value):
    return _WORDS.findall(value)


def pascal(value):
    return "".join(word[:1].upper() + word[1:].lower() if word.isupper() else word[:1].upper() + word[1:] for word in words(value))


def snake(value):
    return "_".join(word.lower() for word in words(value))


def camel(value):
    text = pascal(value)
    return text[:1].lower() + text[1:]


def api_name(value, naming):
    return camel(value) if naming == "camel_case" else snake(value)


def app_label(spec):
    return spec["stack"].get("app_label") or snake(spec["project"]["name"]) or "app"


def namespace(spec):
    return spec["stack"].get("namespace") or pascal(spec["project"]["name"]) or "App"


def entity_by_name(spec, name):
    for entity in spec["entities"]:
        if entity["name"] == name:
            return entity
    return None


def api_projections_markdown(spec):
    """Render derived and transient response contracts for every scaffold target."""
    projections = spec.get("api_projections", [])
    if not projections:
        return "# API projections\n\nNo API projections are defined.\n"
    lines = ["# API projections", "", "These are response contracts, not persistent entities.", ""]
    for projection in projections:
        lines += [
            f"## {projection['resource']}.{projection['endpoint']}: {projection['name']}",
            "",
            f"- Method: `{projection['method']}`",
            f"- Lifecycle: `{projection['lifecycle']}`",
            f"- Sources: {', '.join(projection['sources']) or 'none'}",
        ]
        if projection.get("description"):
            lines.append(f"- {projection['description']}")
        lines += ["", "```json", json.dumps(projection['schema'], indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(lines) + "\n"
