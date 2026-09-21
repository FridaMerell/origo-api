"""Design target: fonts, CSS/TS tokens, Tailwind theme, asset manifest and a style guide."""

import json

from .identity import contrast_report, slug

_TYPE_STEPS = [("xs", -2), ("sm", -1), ("base", 0), ("lg", 1), ("xl", 2), ("2xl", 3), ("3xl", 4), ("4xl", 5)]
_SPACE_STEPS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
_SANS_FALLBACK = "system-ui, sans-serif"
_MONO_FALLBACK = "ui-monospace, monospace"
_DISPLAY_FALLBACK = "Georgia, 'Times New Roman', serif"
_BODY_FALLBACK = "'Helvetica Neue', sans-serif"
_SEMANTIC_DEFAULTS = {
    "light": {
        "background": "#ffffff", "foreground": "#111827", "primary": "#2563eb", "secondary": "#f1f5f9",
        "muted": "#f1f5f9", "accent": "#e0e7ff", "destructive": "#dc2626", "border": "#e2e8f0",
        "input": "#e2e8f0", "ring": "#2563eb", "card": "#ffffff", "popover": "#ffffff",
        "chart-1": "#2563eb", "chart-2": "#16a34a", "chart-3": "#ea580c", "chart-4": "#7c3aed", "chart-5": "#db2777",
    },
    "dark": {
        "background": "#0f172a", "foreground": "#f8fafc", "primary": "#60a5fa", "secondary": "#1e293b",
        "muted": "#1e293b", "accent": "#312e81", "destructive": "#f87171", "border": "#334155",
        "input": "#334155", "ring": "#60a5fa", "card": "#0f172a", "popover": "#0f172a",
        "chart-1": "#60a5fa", "chart-2": "#4ade80", "chart-3": "#fb923c", "chart-4": "#a78bfa", "chart-5": "#f472b6",
    },
}
_SEMANTIC_CANDIDATES = {
    "background": ("background",),
    "foreground": ("text", "foreground"),
    "primary": ("primary",),
    "secondary": ("secondary", "surface"),
    "muted": ("muted", "surface"),
    "accent": ("accent", "secondary", "primary"),
    "destructive": ("danger", "destructive"),
    "border": ("border",),
    "input": ("border",),
    "ring": ("primary", "accent"),
    "card": ("surface", "background"),
    "popover": ("surface", "background"),
    "chart-1": ("primary", "accent"),
    "chart-2": ("secondary", "success", "accent"),
    "chart-3": ("accent", "warning", "secondary"),
    "chart-4": ("success", "primary", "secondary"),
    "chart-5": ("warning", "danger", "accent"),
}
_IDENTITY_DEFAULTS = {
    "name": "Untitled identity", "description": "", "brand_name": "", "tagline": "", "tone": "",
    "theme_modes": "both", "default_mode": "system", "colors": [],
    "heading_font": "", "body_font": "", "mono_font": "", "font_import_url": "", "font_weights": [400, 600, 700],
    "base_font_size": 16, "type_scale_ratio": 1.25, "spacing_unit": 4,
    "radii": {"sm": 4, "md": 8, "lg": 10}, "shadows": {}, "shadows_dark": {},
    "assets": [], "logo_rules": "", "icon_library": "", "icon_style": "",
    "accessibility_target": "AA", "guidelines": "",
}


def _identity(spec):
    identity = spec.get("identity")
    if not identity:
        raise ValueError("This project has no identity: turn on 'include identity' and choose one.")
    return {**_IDENTITY_DEFAULTS, **{key: value for key, value in identity.items() if value is not None}}


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


def _semantic_colors(identity, mode):
    """Resolve identity colours to the roles used by Origo and shadcn-style UI."""
    by_role = {}
    by_name = {}
    for color in identity.get("colors", []):
        value = _value(color, mode)
        if not value:
            continue
        role = color.get("role", "")
        if role and role not in by_role:
            by_role[role] = value
        name = slug(color.get("name", ""))
        if name and name not in by_name:
            by_name[name] = value

    values = {}
    for token, candidates in _SEMANTIC_CANDIDATES.items():
        values[token] = next(
            (by_role[candidate] for candidate in candidates if candidate in by_role),
            next((by_name[candidate] for candidate in candidates if candidate in by_name), _SEMANTIC_DEFAULTS[mode][token]),
        )
    return values


def _global_font(identity, name, fallback):
    font = identity.get(f"{name}_font", "")
    return f'"{font}", {fallback}' if font else fallback


def _global_radius(identity):
    radii = identity.get("radii", {})
    for name in ("lg", "md", "sm"):
        if name in radii:
            return f"{radii[name]}px"
    return "10px"


def _semantic_lines(identity, mode):
    colors = _semantic_colors(identity, mode)
    lines = [f"  --{name}: {value};" for name, value in colors.items()]
    shadows = _shadows(identity, mode)
    lines.append(f"  --shadow-card: {shadows.get('card', '0 1px 3px rgb(15 23 42 / 0.12)')};")
    lines += [f"  --shadow-{name}: {value};" for name, value in shadows.items() if name != "card"]
    return lines


def _brand_fallback_lines(identity, mode):
    """Legacy aliases retained for Flux visualizations that still consume --brand-* tokens."""
    lines = []
    for color in identity["colors"]:
        value = _value(color, mode)
        if value:
            lines.append(f"  --brand-{slug(color['name'])}: {value};")
    lines += [f"  --brand-shadow-{name}: {value};" for name, value in _shadows(identity, mode).items()]
    return lines


def _brand_base_fallback_lines(identity):
    lines = [f"  --brand-font-size-base: {identity['base_font_size']}px;"]
    lines += [f"  --brand-text-{name}: {size};" for name, size in _font_sizes(identity).items()]
    lines.append(f"  --brand-space-unit: {identity['spacing_unit']}px;")
    lines += [f"  --brand-space-{step}: calc(var(--brand-space-unit) * {step});" for step in _SPACE_STEPS]
    lines += [f"  --brand-radius-{name}: {radius}px;" for name, radius in identity["radii"].items()]
    lines += [f"  --brand-font-{name}: {stack};" for name, stack in _fonts(identity).items()]
    return lines


def _theme_selector(identity, mode=None):
    selector = f'[data-theme="{slug(identity["name"]) or "flux"}"]'
    return f'{selector}[data-mode="{mode}"]' if mode else selector


def _origo_color_lines(identity, mode):
    colors = _semantic_colors(identity, mode)
    lines = [
        f"  --bg: {colors['background']};",
        f"  --surface: {colors['card']};",
        f"  --surface-2: {colors['secondary']};",
        f"  --surface-raised: {colors['popover']};",
        f"  --border: {colors['border']};",
        f"  --border-strong: {colors['border']};",
        "  --field-border: var(--border);",
        f"  --text: {colors['foreground']};",
        f"  --text-muted: {colors['muted']};",
        f"  --text-faint: {colors['muted']};",
        f"  --accent: {colors['accent']};",
        f"  --accent-hover: {colors['accent']};",
        f"  --accent-active: {colors['accent']};",
        f"  --accent-contrast: {colors['background']};",
        f"  --accent-wash: {colors['secondary']};",
        f"  --secondary: {colors['secondary']};",
        f"  --secondary-wash: {colors['muted']};",
        f"  --danger: {colors['destructive']};",
        f"  --danger-wash: {colors['muted']};",
        f"  --warning: {_semantic_colors(identity, mode)['chart-3']};",
        f"  --warning-wash: {colors['muted']};",
        f"  --success: {_semantic_colors(identity, mode)['chart-2']};",
        f"  --success-wash: {colors['muted']};",
        f"  --link: {colors['secondary']};",
        f"  --link-hover: {colors['accent']};",
        f"  --focus-ring: {colors['ring']};",
        "  --shadow-color: 0, 0, 0;",
        *[f"  --{name}: {value};" for name, value in colors.items()],
        *_brand_fallback_lines(identity, mode),
    ]
    return lines


def colors_css(spec):
    identity = _identity(spec)
    modes = identity["theme_modes"]
    base_mode = "dark" if modes == "dark" else "light"
    lines = _block(_theme_selector(identity), _origo_color_lines(identity, base_mode))
    if modes == "both":
        lines += [""] + _block(_theme_selector(identity, "dark"), _origo_color_lines(identity, "dark"))
    lines.append("")
    return "\n".join(lines)


def typography_css(spec):
    identity = _identity(spec)
    sizes = _font_sizes(identity)
    md = _number((float(identity["base_font_size"]) / 16) * float(identity["type_scale_ratio"]) ** 0.5) + "rem"
    lines = _block(_theme_selector(identity), [
        f"  --font-display: {_global_font(identity, 'heading', _DISPLAY_FALLBACK)};",
        f"  --font-body: {_global_font(identity, 'body', _BODY_FALLBACK)};",
        f"  --font-mono: {_global_font(identity, 'mono', _MONO_FALLBACK)};",
        f"  --text-xs: {sizes['xs']};", f"  --text-sm: {sizes['sm']};", f"  --text-base: {sizes['base']};", f"  --text-md: {md};",
        f"  --text-lg: {sizes['lg']};", f"  --text-xl: {sizes['xl']};", f"  --text-2xl: {sizes['2xl']};", f"  --text-3xl: {sizes['3xl']};",
        "  --leading-tight: 1.1;", "  --leading-snug: 1.3;", "  --leading-normal: 1.5;", "  --leading-relaxed: 1.65;",
        "  --tracking-tight: -.015em;", "  --tracking-normal: 0;", "  --tracking-wide: .06em;",
        *_brand_base_fallback_lines(identity),
    ])
    lines.append("")
    return "\n".join(lines)


def effects_css(spec):
    identity = _identity(spec)
    def effect_lines(mode):
        shadows = _shadows(identity, mode)
        return [
            f"  --shadow-sm: {shadows.get('sm', '0 1px 1px rgba(var(--shadow-color), .06)')};",
            f"  --shadow-md: {shadows.get('md', '0 1px 3px rgba(var(--shadow-color), .08), 0 1px 2px rgba(var(--shadow-color), .05)')};",
            f"  --shadow-lg: {shadows.get('lg', '0 6px 18px rgba(var(--shadow-color), .10), 0 1px 3px rgba(var(--shadow-color), .06)')};",
            f"  --shadow-card: {shadows.get('card', 'var(--shadow-md)')};",
            "  --ease-standard: cubic-bezier(.35, 0, .25, 1);", "  --duration-fast: 110ms;", "  --duration-normal: 170ms;", "  --border-width: 1px;",
            f"  --radius: {_global_radius(identity)};",
            *[f"  --brand-shadow-{name}: {value};" for name, value in shadows.items()],
        ]

    base_mode = "dark" if identity["theme_modes"] == "dark" else "light"
    lines = _block(_theme_selector(identity), effect_lines(base_mode))
    if identity["theme_modes"] == "both":
        lines += [""] + _block(_theme_selector(identity, "dark"), effect_lines("dark"))
    lines.append("")
    return "\n".join(lines)


def fonts_css(spec):
    identity = _identity(spec)
    lines = []
    if identity["font_import_url"]:
        lines += [f'@import url("{identity["font_import_url"]}");', ""]
    lines.append(":root {")
    lines += [
        f"  --font-heading-family: {_global_font(identity, 'heading', _SANS_FALLBACK)};",
        f"  --font-body-family: {_global_font(identity, 'body', _SANS_FALLBACK)};",
        f"  --font-mono-family: {_global_font(identity, 'mono', _MONO_FALLBACK)};",
    ]
    lines += ["}", ""]
    return "\n".join(lines)


def _block(selector, lines):
    return [f"{selector} {{", *lines, "}"]


def tokens_css(spec):
    """Compatibility entrypoint; it now emits the same standard Origo tokens as globals.css."""
    return globals_css(spec)


def tailwind_css(spec):
    """Tailwind v4 theme backed by the standard semantic CSS variables."""
    identity = _identity(spec)
    lines = []
    if _has(identity, "dark"):
        lines += ['@custom-variant dark (&:where(.dark, .dark *));', ""]
    lines += ["@theme inline {", "  --spacing: var(--spacing-unit);"]
    lines += [f"  --color-{name}: var(--{name});" for name in _SEMANTIC_CANDIDATES]
    lines += ["  --font-sans: var(--font-body-family);", "  --font-heading: var(--font-heading-family);", "  --font-mono: var(--font-mono-family);"]
    lines += [f"  --text-{name}: var(--font-size-{name});" for name, _ in _TYPE_STEPS]
    lines += ["  --radius-sm: calc(var(--radius) - 4px);", "  --radius-md: calc(var(--radius) - 2px);", "  --radius-lg: var(--radius);"]
    lines += [f"  --shadow-elevation-{name}: var(--shadow-{name});" for name in {"card", *_shadows(identity, "light"), *_shadows(identity, "dark")}]
    lines += ["}", ""]
    return "\n".join(lines)


def globals_css(spec):
    """Tailwind entrypoint layered on the scoped Origo token files."""
    identity = _identity(spec)
    lines = []
    if identity.get("font_import_url"):
        lines.append(f'@import url("{identity["font_import_url"]}");')
    lines += [
        '@import "tailwindcss";',
        '@import "../identity/colors.css";',
        '@import "../identity/typography.css";',
        '@import "../identity/effects.css";',
        "",
    ]
    if _has(identity, "dark"):
        lines += ['@custom-variant dark (&:where([data-mode="dark"], [data-mode="dark"] *));', ""]
    lines += [
        "@theme inline {",
        "  --color-background: var(--bg);",
        "  --color-foreground: var(--text);",
        "  --color-primary: var(--accent);",
        "  --color-secondary: var(--secondary);",
        "  --color-muted: var(--text-muted);",
        "  --color-accent: var(--accent);",
        "  --color-destructive: var(--danger);",
        "  --color-border: var(--border);",
        "  --color-input: var(--field-border);",
        "  --color-ring: var(--focus-ring);",
        "  --color-card: var(--surface);",
        "  --color-popover: var(--surface-raised);",
        "  --font-sans: var(--font-body);",
        "  --font-heading: var(--font-display);",
        "  --font-mono: var(--font-mono);",
        "  --radius-sm: calc(var(--radius) - 4px);",
        "  --radius-md: calc(var(--radius) - 2px);",
        "  --radius-lg: var(--radius);",
    ]
    lines += ["}", ""]
    return "\n".join(lines)


def tailwind_ts(spec):
    """Theme object for ``tailwind.config.ts`` (``theme.extend``), backed by the same variables."""
    identity = _identity(spec)
    shadow_names = {"card", *_shadows(identity, "light"), *_shadows(identity, "dark")}
    theme = {
        "colors": {name: f"var(--{name})" for name in _SEMANTIC_CANDIDATES},
        "fontFamily": {"sans": ["var(--font-body-family)"], "heading": ["var(--font-heading-family)"], "mono": ["var(--font-mono-family)"]},
        "fontSize": {name: f"var(--font-size-{name})" for name, _ in _TYPE_STEPS},
        "borderRadius": {"sm": "calc(var(--radius) - 4px)", "md": "calc(var(--radius) - 2px)", "lg": "var(--radius)"},
        "boxShadow": {f"elevation-{name}": f"var(--shadow-{name})" for name in shadow_names},
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
                f"`--{color['role'] or token}` | semantic Tailwind utility |"
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

    lines += ["## Shape", "", f"- Spacing unit: {identity['spacing_unit']}px (`--spacing-unit`)"]
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
        "- Reference the semantic CSS variables and Tailwind utilities so the theme switches automatically.",
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
        {"path": "app/globals.css", "content": globals_css(spec)},
        {"path": "identity/colors.css", "content": colors_css(spec)},
        {"path": "identity/typography.css", "content": typography_css(spec)},
        {"path": "identity/effects.css", "content": effects_css(spec)},
        {"path": "identity/tailwind.theme.ts", "content": tailwind_ts(spec)},
        {"path": "identity/tokens.ts", "content": tokens_ts(spec)},
        {"path": "identity/STYLEGUIDE.md", "content": styleguide(spec)},
    ]
    if identity["assets"] or identity["icon_library"] or identity["logo_rules"]:
        files.append({"path": "identity/assets.ts", "content": assets_ts(spec)})
    return files
