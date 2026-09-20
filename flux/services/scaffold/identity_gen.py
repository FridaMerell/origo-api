"""Design target: fonts, CSS/TS tokens, Tailwind theme, asset manifest and a style guide."""

import json

from .identity import contrast_report, slug

_TYPE_STEPS = [("xs", -2), ("sm", -1), ("base", 0), ("lg", 1), ("xl", 2), ("2xl", 3), ("3xl", 4), ("4xl", 5)]
_SPACE_STEPS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
_SANS_FALLBACK = "system-ui, sans-serif"
_MONO_FALLBACK = "ui-monospace, monospace"


def _identity(spec):
    identity = spec.get("identity")
    if not identity:
        raise ValueError("This project has no identity: turn on 'include identity' and choose one.")
    return identity


def _number(value):
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _font_sizes(identity):
    base = identity["base_font_size"] / 16
    ratio = float(identity["type_scale_ratio"])
    return {name: f"{_number(base * ratio ** step)}rem" for name, step in _TYPE_STEPS}


def _fonts(identity):
    fonts = {}
    if identity["heading_font"]:
        fonts["heading"] = f'"{identity["heading_font"]}", {_SANS_FALLBACK}'
    if identity["body_font"]:
        fonts["body"] = f'"{identity["body_font"]}", {_SANS_FALLBACK}'
    if identity["mono_font"]:
        fonts["mono"] = f'"{identity["mono_font"]}", {_MONO_FALLBACK}'
    return fonts


def _has(identity, mode):
    return identity["theme_modes"] in (mode, "both")


def _value(color, mode):
    """Colour for a mode; falls back to the other value so a variable is never left undefined."""
    if mode == "dark":
        return color["dark"] or color["light"]
    return color["light"] or color["dark"]


def _shadows(identity, mode):
    shadows = dict(identity["shadows"])
    if mode == "dark":
        shadows.update(identity["shadows_dark"])
    return shadows


def _mode_vars(identity, mode):
    lines = []
    for color in identity["colors"]:
        value = _value(color, mode)
        if value:
            lines.append(f"  --brand-{slug(color['name'])}: {value};")
    lines += [f"  --brand-shadow-{name}: {value};" for name, value in _shadows(identity, mode).items()]
    return lines


def _base_vars(identity):
    lines = [f"  --brand-font-size-base: {identity['base_font_size']}px;"]
    lines += [f"  --brand-text-{name}: {size};" for name, size in _font_sizes(identity).items()]
    lines.append(f"  --brand-space-unit: {identity['spacing_unit']}px;")
    lines += [f"  --brand-space-{step}: calc(var(--brand-space-unit) * {step});" for step in _SPACE_STEPS]
    lines += [f"  --brand-radius-{name}: {radius}px;" for name, radius in identity["radii"].items()]
    return lines


def fonts_css(spec):
    identity = _identity(spec)
    lines = []
    if identity["font_import_url"]:
        lines += [f'@import url("{identity["font_import_url"]}");', ""]
    lines.append(":root {")
    lines += [f"  --brand-font-{name}: {stack};" for name, stack in _fonts(identity).items()]
    lines += ["}", ""]
    return "\n".join(lines)


def _block(selector, lines):
    return [f"{selector} {{", *lines, "}"]


def tokens_css(spec):
    """Variables for the identity's theme modes.

    One mode: ``:root`` carries it. Both modes: the default mode sits on ``:root`` and the other is
    switched on with ``data-theme`` (and, when the default follows the system, by ``prefers-color-scheme``).
    """
    identity = _identity(spec)
    modes, default = identity["theme_modes"], identity["default_mode"]
    base = _base_vars(identity)
    if modes != "both":
        lines = _block(":root", [f"  color-scheme: {modes};", *_mode_vars(identity, modes), *base])
    else:
        light, dark = _mode_vars(identity, "light"), _mode_vars(identity, "dark")
        if default == "dark":
            lines = _block(":root", ["  color-scheme: dark;", *dark, *base])
            lines += [""] + _block(':root[data-theme="light"]', ["  color-scheme: light;", *light])
        elif default == "light":
            lines = _block(":root", ["  color-scheme: light;", *light, *base])
            lines += [""] + _block(':root[data-theme="dark"]', ["  color-scheme: dark;", *dark])
        else:
            lines = _block(":root", ["  color-scheme: light dark;", *light, *base])
            lines += ["", "@media (prefers-color-scheme: dark) {"]
            lines += [f"  {line}" for line in _block(':root:not([data-theme="light"])', dark)]
            lines += ["}", ""]
            lines += _block(':root[data-theme="light"]', ["  color-scheme: light;"])
            lines += [""] + _block(':root[data-theme="dark"]', ["  color-scheme: dark;", *dark])
    lines.append("")
    return "\n".join(lines)


def tailwind_css(spec):
    """Tailwind v4 theme: utilities resolve through the ``--brand-*`` variables so theme switching keeps working."""
    identity = _identity(spec)
    lines = []
    if identity["theme_modes"] == "both" and identity["default_mode"] != "system":
        lines += ['@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));', ""]
    lines += ["@theme inline {", "  --spacing: var(--brand-space-unit);"]
    lines += [f"  --color-{slug(color['name'])}: var(--brand-{slug(color['name'])});" for color in identity["colors"]]
    lines += [f"  --font-{name}: var(--brand-font-{name});" for name in _fonts(identity)]
    lines += [f"  --text-{name}: var(--brand-text-{name});" for name, _ in _TYPE_STEPS]
    lines += [f"  --radius-{name}: var(--brand-radius-{name});" for name in identity["radii"]]
    lines += [f"  --shadow-{name}: var(--brand-shadow-{name});" for name in _shadows(identity, "light") | _shadows(identity, "dark")]
    lines += ["}", ""]
    return "\n".join(lines)


def tailwind_ts(spec):
    """Theme object for ``tailwind.config.ts`` (``theme.extend``), backed by the same variables."""
    identity = _identity(spec)
    shadow_names = list(_shadows(identity, "light") | _shadows(identity, "dark"))
    theme = {
        "colors": {slug(c["name"]): f"var(--brand-{slug(c['name'])})" for c in identity["colors"]},
        "fontFamily": {name: [stack] for name, stack in _fonts(identity).items()},
        "fontSize": {name: f"var(--brand-text-{name})" for name, _ in _TYPE_STEPS},
        "borderRadius": {name: f"var(--brand-radius-{name})" for name in identity["radii"]},
        "boxShadow": {name: f"var(--brand-shadow-{name})" for name in shadow_names},
    }
    return f"export const brandTheme = {json.dumps(theme, indent=2)} as const;\n"


def tokens_ts(spec):
    identity = _identity(spec)

    def colors(mode):
        if not _has(identity, mode):
            return {}
        return {slug(c["name"]): _value(c, mode) for c in identity["colors"] if _value(c, mode)}

    tokens = {
        "modes": identity["theme_modes"],
        "defaultMode": identity["default_mode"],
        "colors": {"light": colors("light"), "dark": colors("dark")},
        "fonts": {
            "heading": identity["heading_font"],
            "body": identity["body_font"],
            "mono": identity["mono_font"],
            "weights": identity["font_weights"],
        },
        "fontSizes": _font_sizes(identity),
        "spacingUnit": identity["spacing_unit"],
        "radii": identity["radii"],
        "shadows": {
            "light": _shadows(identity, "light") if _has(identity, "light") else {},
            "dark": _shadows(identity, "dark") if _has(identity, "dark") else {},
        },
    }
    return f"export const tokens = {json.dumps(tokens, indent=2)} as const;\n"


def _asset(asset):
    return {"mode": "any", **asset}


def assets_ts(spec):
    identity = _identity(spec)
    manifest = {
        "assets": [_asset(asset) for asset in identity["assets"]],
        "icons": {"library": identity["icon_library"], "style": identity["icon_style"]},
        "logoRules": identity["logo_rules"],
    }
    return f"export const brandAssets = {json.dumps(manifest, indent=2, ensure_ascii=False)} as const;\n"


_MODE_LABELS = {"light": "Light only", "dark": "Dark only", "both": "Light and dark"}
_DEFAULT_LABELS = {"system": "follows the system setting", "light": "light", "dark": "dark"}


def styleguide(spec):
    identity = _identity(spec)
    modes, default = identity["theme_modes"], identity["default_mode"]
    title = identity["brand_name"] or identity["name"]
    lines = [f"# Visual identity: {title}", ""]
    if identity["tagline"]:
        lines += [f"_{identity['tagline']}_", ""]
    if identity["description"]:
        lines += [identity["description"], ""]
    if identity["tone"]:
        lines += ["## Tone of voice", "", identity["tone"], ""]

    lines += ["## Themes", "", f"- Modes: **{_MODE_LABELS[modes]}**"]
    if modes == "both":
        lines += [
            f"- Default: {_DEFAULT_LABELS[default]}",
            '- Switch by setting `data-theme="light"` or `data-theme="dark"` on `<html>`.',
        ]
    lines.append("")

    if identity["colors"]:
        lines += ["## Colors", "", "| Name | Role | Light | Dark | CSS variable | Tailwind |", "|---|---|---|---|---|---|"]
        for color in identity["colors"]:
            token = slug(color["name"])
            light = f"`{color['light']}`" if _has(identity, "light") and color["light"] else "-"
            dark = f"`{color['dark']}`" if _has(identity, "dark") and color["dark"] else "-"
            lines.append(
                f"| {color['name']} | {color['role'] or '-'} | {light} | {dark} | "
                f"`--brand-{token}` | `bg-{token}`, `text-{token}` |"
            )
        report = contrast_report(identity["colors"], identity["accessibility_target"], modes)
        if report:
            lines += ["", f"### Contrast (target WCAG {identity['accessibility_target']})", "", "| Mode | Pair | Ratio | Required | Result |", "|---|---|---|---|---|"]
            for row in report:
                lines.append(
                    f"| {row['mode']} | {row['foreground']} on {row['background']} | {row['ratio']}:1 | "
                    f"{row['required']}:1 | {'pass' if row['passed'] else '**fails**'} |"
                )
        lines.append("")

    fonts = _fonts(identity)
    lines += ["## Typography", ""]
    for label, key in (("Headings", "heading_font"), ("Body", "body_font"), ("Monospace", "mono_font")):
        if identity[key]:
            lines.append(f"- {label}: **{identity[key]}**")
    lines.append(f"- Weights: {', '.join(str(w) for w in identity['font_weights'])}")
    lines += [f"- Base size {identity['base_font_size']}px, scale ratio {_number(float(identity['type_scale_ratio']))}", ""]
    lines += ["| Step | Size |", "|---|---|"]
    lines += [f"| `{name}` | {size} |" for name, size in _font_sizes(identity).items()]
    lines.append("")
    if fonts:
        lines += ["Load fonts with `fonts.css`; do not add other typefaces.", ""]

    lines += ["## Shape", "", f"- Spacing unit: {identity['spacing_unit']}px (`--brand-space-N` = N units)"]
    lines += [f"- Radius `{name}`: {radius}px" for name, radius in identity["radii"].items()]
    light_shadows, dark_shadows = _shadows(identity, "light"), _shadows(identity, "dark")
    for name in light_shadows | dark_shadows:
        entry = f"- Shadow `{name}`: `{light_shadows.get(name, '-')}`"
        if _has(identity, "dark") and dark_shadows.get(name) != light_shadows.get(name):
            entry += f", dark: `{dark_shadows.get(name, '-')}`"
        lines.append(entry)
    lines.append("")

    if identity["assets"] or identity["logo_rules"] or identity["icon_library"]:
        lines += ["## Logo and icons", ""]
        if identity["assets"]:
            lines += ["| Name | Kind | Mode | File | Usage |", "|---|---|---|---|---|"]
            lines += [
                f"| {a['name']} | {a['kind']} | {a.get('mode', 'any')} | `{a['url']}` | {a['usage'] or '-'} |"
                for a in identity["assets"]
            ]
            if any(a.get("mode", "any") != "any" for a in identity["assets"]):
                lines += ["", "Use the `light` variant on light backgrounds and the `dark` variant on dark backgrounds."]
            lines.append("")
        if identity["logo_rules"]:
            lines += ["**Logo rules:** " + identity["logo_rules"], ""]
        if identity["icon_library"]:
            style = f", {identity['icon_style']} style" if identity["icon_style"] else ""
            lines += [f"Icons: **{identity['icon_library']}**{style}. Do not mix icon sets.", ""]

    if identity["guidelines"]:
        lines += ["## Guidelines", "", identity["guidelines"], ""]

    lines += [
        "## Rules for building UI",
        "",
        "- Use the tokens (`tokens.css`, Tailwind theme). Never hard-code colors, font sizes, radii or shadows.",
        "- Reference colors through the `--brand-*` variables so the theme switches automatically.",
    ]
    if modes == "both":
        lines.append("- Every screen must work in both light and dark mode; check both before shipping.")
    lines += [
        f"- Text and interactive colors must meet WCAG {identity['accessibility_target']} contrast in every supported mode.",
        "- Use logos and icons only as described above.",
        "",
    ]
    return "\n".join(lines)


def generate(spec):
    identity = _identity(spec)
    files = [
        {"path": "identity/fonts.css", "content": fonts_css(spec)},
        {"path": "identity/tokens.css", "content": tokens_css(spec)},
        {"path": "identity/tailwind.theme.css", "content": tailwind_css(spec)},
        {"path": "identity/tailwind.theme.ts", "content": tailwind_ts(spec)},
        {"path": "identity/tokens.ts", "content": tokens_ts(spec)},
        {"path": "identity/STYLEGUIDE.md", "content": styleguide(spec)},
    ]
    if identity["assets"] or identity["icon_library"] or identity["logo_rules"]:
        files.append({"path": "identity/assets.ts", "content": assets_ts(spec)})
    return files
