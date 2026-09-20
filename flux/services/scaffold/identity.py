"""Validation and accessibility maths for visual identities. Pure: no Django imports."""

import re

COLOR_ROLES = ["primary", "secondary", "accent", "background", "surface", "text", "muted", "border", "success", "warning", "danger"]
ASSET_KINDS = ["logo", "logo_mark", "icon", "favicon", "illustration", "other"]
ASSET_MODES = ["any", "light", "dark"]
THEME_MODES = ["light", "dark", "both"]
DEFAULT_MODES = ["system", "light", "dark"]
FONT_WEIGHTS = [100, 200, 300, 400, 500, 600, 700, 800, 900]

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_TOKEN_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FONT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,119}$")
_URL = re.compile(r"^(?:https://|/)[^\s\"'()<>;{}\\]+$")
_UNSAFE_CSS = re.compile(r"[;{}<>\\]|/\*|\*/|url\(|@import", re.IGNORECASE)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _list_of_dicts(value, label):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects.")
    return value


def _text(item, key, label, *, required=False, maximum=200):
    value = item.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label}.{key} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label}.{key} is required.")
    if len(value) > maximum:
        raise ValueError(f"{label}.{key} must be at most {maximum} characters.")
    return value


def clean_colors(value, modes="both"):
    """Validate colours. ``modes`` decides which values are required: ``light``, ``dark`` or ``both``."""
    if modes not in THEME_MODES:
        raise ValueError(f"theme_modes must be one of: {', '.join(THEME_MODES)}.")
    seen = set()
    cleaned = []
    for item in _list_of_dicts(value, "colors"):
        name = _text(item, "name", "color", required=True, maximum=60)
        token = slug(name)
        if not token:
            raise ValueError(f"color.name {name!r} must contain letters or digits.")
        if token in seen:
            raise ValueError(f"Duplicate color name: {name}.")
        seen.add(token)
        role = _text(item, "role", "color", maximum=30)
        if role and role not in COLOR_ROLES:
            raise ValueError(f"color.role must be one of: {', '.join(COLOR_ROLES)}.")
        light = _text(item, "light", "color", required=modes != "dark", maximum=7)
        dark = _text(item, "dark", "color", required=modes != "light", maximum=7)
        for label, color in (("light", light), ("dark", dark)):
            if color and not _HEX.match(color):
                raise ValueError(f"color.{label} must be a #RRGGBB hex value, got {color!r}.")
        cleaned.append({"name": name, "role": role, "light": light.lower(), "dark": dark.lower()})
    return cleaned


def clean_font_name(value, label="font"):
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _FONT_NAME.match(value.strip()):
        raise ValueError(f"{label} may only contain letters, digits, spaces, hyphens and underscores.")
    return value.strip()


def clean_import_url(value):
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _URL.match(value.strip()) or len(value) > 500:
        raise ValueError("font_import_url must be an https:// or root-relative URL without quotes or spaces.")
    return value.strip()


def clean_font_weights(value):
    if not isinstance(value, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ValueError("font_weights must be a list of integers.")
    unknown = sorted(set(value) - set(FONT_WEIGHTS))
    if unknown:
        raise ValueError(f"font_weights may only contain 100-900 in steps of 100, got {unknown}.")
    return sorted(set(value))


def _token_map(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    for key in value:
        if not isinstance(key, str) or not _TOKEN_NAME.match(key):
            raise ValueError(f"{label} keys must be lowercase words joined by hyphens, got {key!r}.")
    return value


def clean_radii(value):
    _token_map(value, "radii")
    cleaned = {}
    for key, radius in value.items():
        if isinstance(radius, bool) or not isinstance(radius, int) or not 0 <= radius <= 999:
            raise ValueError(f"radii.{key} must be an integer number of pixels between 0 and 999.")
        cleaned[key] = radius
    return cleaned


def clean_shadows(value):
    _token_map(value, "shadows")
    cleaned = {}
    for key, shadow in value.items():
        if not isinstance(shadow, str) or not shadow.strip() or len(shadow) > 200 or _UNSAFE_CSS.search(shadow):
            raise ValueError(f"shadows.{key} must be a plain CSS box-shadow value.")
        cleaned[key] = shadow.strip()
    return cleaned


def clean_assets(value):
    cleaned = []
    for item in _list_of_dicts(value, "assets"):
        kind = _text(item, "kind", "asset", maximum=30) or "other"
        if kind not in ASSET_KINDS:
            raise ValueError(f"asset.kind must be one of: {', '.join(ASSET_KINDS)}.")
        url = _text(item, "url", "asset", required=True, maximum=500)
        if not _URL.match(url):
            raise ValueError("asset.url must be an https:// or root-relative URL without quotes or spaces.")
        mode = _text(item, "mode", "asset", maximum=10) or "any"
        if mode not in ASSET_MODES:
            raise ValueError(f"asset.mode must be one of: {', '.join(ASSET_MODES)}.")
        cleaned.append(
            {
                "name": _text(item, "name", "asset", required=True, maximum=80),
                "kind": kind,
                "mode": mode,
                "url": url,
                "usage": _text(item, "usage", "asset", maximum=500),
            }
        )
    return cleaned


def _linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(color):
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def contrast_ratio(first, second):
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


_TEXT_PAIRS = [("text", "background"), ("text", "surface"), ("muted", "background")]
_UI_PAIRS = [("primary", "background"), ("accent", "background")]


def contrast_report(colors, target, theme_modes=None):
    """WCAG contrast for the role pairs that exist. ``target`` is ``AA`` or ``AAA``.

    ``theme_modes`` (``light``, ``dark`` or ``both``) decides which modes are checked; without it,
    dark is checked when any colour has a dark value.
    """
    text_required, ui_required = (7.0, 4.5) if target == "AAA" else (4.5, 3.0)
    if theme_modes == "dark":
        modes = ["dark"]
    elif theme_modes == "light":
        modes = ["light"]
    elif theme_modes == "both":
        modes = ["light", "dark"]
    else:
        modes = ["light"] + (["dark"] if any(color["dark"] for color in colors) else [])
    report = []
    for mode in modes:
        by_role = {}
        for color in colors:
            value = color["dark"] or color["light"] if mode == "dark" else color["light"]
            if color["role"] and color["role"] not in by_role:
                by_role[color["role"]] = value
        for pairs, required in ((_TEXT_PAIRS, text_required), (_UI_PAIRS, ui_required)):
            for foreground, background in pairs:
                if foreground in by_role and background in by_role:
                    ratio = contrast_ratio(by_role[foreground], by_role[background])
                    report.append(
                        {
                            "mode": mode,
                            "foreground": foreground,
                            "background": background,
                            "ratio": round(ratio, 2),
                            "required": required,
                            "passed": ratio >= required,
                        }
                    )
    return report
