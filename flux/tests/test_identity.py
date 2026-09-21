"""Visual identity validation and generators are pure, so these tests need no database."""

import unittest

from flux.services.scaffold import ScaffoldError, generate_files
from flux.services.scaffold.identity import (
    clean_assets,
    clean_colors,
    clean_font_name,
    clean_font_weights,
    clean_import_url,
    clean_radii,
    clean_shadows,
    contrast_ratio,
    contrast_report,
)
from flux.tests.test_scaffold import make_spec


def make_identity(**overrides):
    identity = {
        'name': 'Origo', 'description': 'The Origo look.', 'brand_name': 'Origo', 'tagline': 'Start here',
        'tone': 'Warm and direct.', 'theme_modes': 'both', 'default_mode': 'system',
        'colors': [
            {'name': 'Primary', 'role': 'primary', 'light': '#0b5fff', 'dark': '#6b9dff'},
            {'name': 'Background', 'role': 'background', 'light': '#ffffff', 'dark': '#0b0d12'},
            {'name': 'Surface', 'role': 'surface', 'light': '#f4f5f7', 'dark': '#151821'},
            {'name': 'Text', 'role': 'text', 'light': '#111318', 'dark': '#f2f3f5'},
        ],
        'heading_font': 'Fraunces', 'body_font': 'Inter', 'mono_font': '',
        'font_import_url': 'https://fonts.googleapis.com/css2?family=Inter&display=swap',
        'font_weights': [400, 700], 'base_font_size': 16, 'type_scale_ratio': 1.25,
        'spacing_unit': 4, 'radii': {'sm': 4, 'md': 8}, 'shadows': {'card': '0 1px 3px rgba(0,0,0,0.2)'},
        'shadows_dark': {},
        'assets': [{'name': 'Logo', 'kind': 'logo', 'mode': 'any', 'url': '/brand/logo.svg', 'usage': 'On light backgrounds.'}],
        'logo_rules': 'Minimum 24px high.', 'icon_library': 'lucide', 'icon_style': 'outline',
        'accessibility_target': 'AA', 'guidelines': 'Prefer photography over illustration.',
    }
    identity.update(overrides)
    return identity


def design_files(identity=None, target='design'):
    spec = make_spec(identity=identity if identity is not None else make_identity())
    return {item['path']: item['content'] for item in generate_files(spec, target)}


class ValidationTests(unittest.TestCase):
    def test_colors_are_normalised(self):
        colors = clean_colors([{'name': 'Primary', 'role': 'primary', 'light': '#0B5FFF'}], 'light')

        self.assertEqual(colors, [{'name': 'Primary', 'role': 'primary', 'light': '#0b5fff', 'dark': ''}])

    def test_colors_reject_bad_hex_roles_and_duplicates(self):
        for bad in (
            [{'name': 'A', 'light': 'red'}],
            [{'name': 'A', 'light': '#fff'}],
            [{'name': 'A', 'light': '#ffffff', 'dark': 'blue'}],
            [{'name': 'A', 'role': 'hero', 'light': '#ffffff'}],
            [{'name': 'A', 'light': '#ffffff'}, {'name': 'a', 'light': '#000000'}],
            [{'name': '', 'light': '#ffffff'}],
            'not a list',
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_colors(bad)

    def test_font_names_and_urls_cannot_break_out_of_css(self):
        for bad in ('Inter"; } body { display:none', 'A;B', 'A{B}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_font_name(bad)
        for bad in ('http://insecure.example/f.css', 'https://x.example/f.css"); body{x', 'javascript:alert(1)', 'https://a b'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_import_url(bad)
        self.assertEqual(clean_font_name(' Fira Sans '), 'Fira Sans')

    def test_shadows_reject_css_injection(self):
        for bad in ('0 0 1px red; } body { color: red', '0 0 1px url(x)', '/* x */ 0 0 1px red'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_shadows({'card': bad})
        with self.assertRaises(ValueError):
            clean_shadows({'Bad Name': '0 0 1px red'})

    def test_radii_weights_and_assets(self):
        self.assertEqual(clean_radii({'sm': 4}), {'sm': 4})
        with self.assertRaises(ValueError):
            clean_radii({'sm': -1})
        with self.assertRaises(ValueError):
            clean_radii({'sm': True})
        self.assertEqual(clean_font_weights([700, 400, 400]), [400, 700])
        with self.assertRaises(ValueError):
            clean_font_weights([450])
        with self.assertRaises(ValueError):
            clean_assets([{'name': 'x', 'url': 'javascript:alert(1)'}])
        with self.assertRaises(ValueError):
            clean_assets([{'name': 'x', 'kind': 'banner', 'url': '/x.svg'}])
        self.assertEqual(clean_assets([{'name': 'Logo', 'url': '/logo.svg'}])[0]['kind'], 'other')


class ContrastTests(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(contrast_ratio('#000000', '#ffffff'), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio('#777777', '#ffffff'), 4.48, places=2)

    def test_report_flags_failures_against_the_target(self):
        colors = clean_colors([
            {'name': 'Text', 'role': 'text', 'light': '#777777'},
            {'name': 'Background', 'role': 'background', 'light': '#ffffff'},
        ], 'light')

        aa = contrast_report(colors, 'AA')
        aaa = contrast_report(colors, 'AAA')

        self.assertEqual([row['passed'] for row in aa], [False])
        self.assertEqual(aaa[0]['required'], 7.0)

    def test_dark_mode_is_only_reported_when_dark_colors_exist(self):
        light_only = clean_colors([
            {'name': 'Text', 'role': 'text', 'light': '#000000'},
            {'name': 'Background', 'role': 'background', 'light': '#ffffff'},
        ], 'light')

        self.assertEqual({row['mode'] for row in contrast_report(light_only, 'AA')}, {'light'})
        self.assertEqual({row['mode'] for row in contrast_report(clean_colors(make_identity()['colors']), 'AA')}, {'light', 'dark'})


class DesignGeneratorTests(unittest.TestCase):
    def test_design_target_needs_an_identity(self):
        with self.assertRaises(ScaffoldError):
            generate_files(make_spec(), 'design')
        with self.assertRaises(ScaffoldError):
            generate_files(make_spec(identity=None), 'design')

    def test_all_files_are_generated(self):
        self.assertEqual(
            sorted(design_files()),
            [
                'app/globals.css', 'identity/STYLEGUIDE.md', 'identity/assets.ts', 'identity/fonts.css', 'identity/tailwind.theme.css',
                'identity/tailwind.theme.ts', 'identity/tokens.css', 'identity/tokens.ts',
            ],
        )

    def test_globals_css_is_an_origo_tailwind_entrypoint_with_semantic_tokens(self):
        css = design_files()['app/globals.css']

        self.assertIn('@import "tailwindcss";', css)
        self.assertIn('@theme inline {', css)
        self.assertIn('--color-background: var(--background);', css)
        self.assertIn('--color-card: var(--card);', css)
        self.assertIn('--color-chart-5: var(--chart-5);', css)
        self.assertIn('--font-sans: var(--font-body-family);', css)
        self.assertIn('--radius-md: calc(var(--radius) - 2px);', css)
        self.assertIn(':root {\n  color-scheme: light;\n  --background: #ffffff;', css)
        self.assertIn('.dark, :root[data-theme="dark"] {', css)
        self.assertIn('--primary: #6b9dff;', css)

    def test_globals_css_uses_stable_defaults_when_roles_are_absent(self):
        css = design_files(make_identity(colors=[], heading_font='', body_font='', mono_font='', radii={}, shadows={}))['app/globals.css']

        self.assertIn('--destructive: #dc2626;', css)
        self.assertIn('--font-body-family: system-ui, sans-serif;', css)
        self.assertIn('--radius: 10px;', css)

    def test_globals_css_tolerates_a_sparse_legacy_identity(self):
        css = design_files({'name': 'Legacy'})['app/globals.css']

        self.assertIn('--background: #ffffff;', css)
        self.assertIn('.dark, :root[data-theme="dark"] {', css)

    def test_globals_css_only_emits_the_dark_class_for_dark_capable_identities(self):
        light = design_files(make_identity(theme_modes='light', colors=LIGHT_ONLY))['app/globals.css']
        dark = design_files(make_identity(theme_modes='dark', colors=DARK_ONLY))['app/globals.css']

        self.assertNotIn('.dark, :root[data-theme="dark"]', light)
        self.assertIn(':root {\n  color-scheme: dark;', dark)
        self.assertIn('.dark, :root[data-theme="dark"] {', dark)

    def test_tokens_css_has_light_and_dark_values(self):
        css = design_files()['identity/tokens.css']

        self.assertIn('--primary: #0b5fff;', css)
        self.assertIn('--primary: #6b9dff;', css)
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn('prefers-color-scheme: dark', css)
        self.assertIn('--radius: 8px;', css)
        self.assertIn('--shadow-card: 0 1px 3px rgba(0,0,0,0.2);', css)
        self.assertIn('--font-size-lg: 1.25rem;', css)
        self.assertIn('--font-size-sm: 0.8rem;', css)

    def test_light_only_identity_has_no_dark_block(self):
        colors = [{'name': 'Text', 'role': 'text', 'light': '#000000', 'dark': ''}]

        css = design_files(make_identity(colors=colors, theme_modes='light'))['identity/tokens.css']

        self.assertNotIn('prefers-color-scheme', css)
        self.assertNotIn('data-theme="dark"', css)

    def test_fonts_css_imports_first_and_defines_families(self):
        css = design_files()['identity/fonts.css']

        self.assertTrue(css.startswith('@import url("https://fonts.googleapis.com'))
        self.assertIn('--font-heading-family: "Fraunces", system-ui, sans-serif;', css)
        self.assertIn('--font-mono-family: ui-monospace, monospace;', css)

    def test_tailwind_v4_theme_maps_through_the_brand_variables(self):
        css = design_files()['identity/tailwind.theme.css']

        self.assertIn('@theme inline {', css)
        self.assertIn('--color-primary: var(--primary);', css)
        self.assertIn('--font-heading: var(--font-heading-family);', css)
        self.assertIn('--radius-md: calc(var(--radius) - 2px);', css)
        self.assertIn('--shadow-elevation-card: var(--shadow-card);', css)

    def test_typescript_files_are_generated(self):
        files = design_files()

        self.assertIn('"primary": "var(--primary)"', files['identity/tailwind.theme.ts'])
        self.assertIn('export const tokens = {', files['identity/tokens.ts'])
        self.assertIn('"primary": "#6b9dff"', files['identity/tokens.ts'])
        self.assertIn('"library": "lucide"', files['identity/assets.ts'])

    def test_assets_file_is_omitted_without_assets_or_icons(self):
        identity = make_identity(assets=[], logo_rules='', icon_library='')

        self.assertNotIn('identity/assets.ts', design_files(identity))

    def test_styleguide_documents_the_identity_and_its_contrast(self):
        guide = design_files()['identity/STYLEGUIDE.md']

        self.assertIn('# Visual identity: Origo', guide)
        self.assertIn('Warm and direct.', guide)
        self.assertIn('| Primary | primary | `#0b5fff` | `#6b9dff` | `--primary` |', guide)
        self.assertIn('text on background', guide)
        self.assertIn('Minimum 24px high.', guide)
        self.assertIn('lucide', guide)
        self.assertIn('Prefer photography over illustration.', guide)
        self.assertIn('Never hard-code colors', guide)

    def test_styleguide_marks_failing_contrast(self):
        colors = [
            {'name': 'Text', 'role': 'text', 'light': '#aaaaaa', 'dark': ''},
            {'name': 'Background', 'role': 'background', 'light': '#ffffff', 'dark': ''},
        ]

        self.assertIn('**fails**', design_files(make_identity(colors=colors))['identity/STYLEGUIDE.md'])


LIGHT_ONLY = [
    {'name': 'Text', 'role': 'text', 'light': '#111111', 'dark': ''},
    {'name': 'Background', 'role': 'background', 'light': '#ffffff', 'dark': ''},
]
DARK_ONLY = [
    {'name': 'Text', 'role': 'text', 'light': '', 'dark': '#eeeeee'},
    {'name': 'Background', 'role': 'background', 'light': '', 'dark': '#0b0d12'},
]


class ThemeModeValidationTests(unittest.TestCase):
    def test_both_modes_require_a_light_and_a_dark_value_for_every_colour(self):
        with self.assertRaises(ValueError):
            clean_colors([{'name': 'A', 'light': '#ffffff'}], 'both')
        with self.assertRaises(ValueError):
            clean_colors([{'name': 'A', 'dark': '#000000'}], 'both')
        self.assertEqual(len(clean_colors([{'name': 'A', 'light': '#ffffff', 'dark': '#000000'}], 'both')), 1)

    def test_light_only_needs_no_dark_and_dark_only_needs_no_light(self):
        self.assertEqual(clean_colors(LIGHT_ONLY, 'light')[0]['dark'], '')
        self.assertEqual(clean_colors(DARK_ONLY, 'dark')[0]['light'], '')

    def test_dark_only_still_requires_the_dark_value(self):
        with self.assertRaises(ValueError):
            clean_colors([{'name': 'A', 'light': '#ffffff'}], 'dark')

    def test_unknown_modes_are_rejected(self):
        with self.assertRaises(ValueError):
            clean_colors([], 'sepia')

    def test_asset_modes(self):
        self.assertEqual(clean_assets([{'name': 'Logo', 'url': '/l.svg'}])[0]['mode'], 'any')
        self.assertEqual(clean_assets([{'name': 'Logo', 'url': '/l.svg', 'mode': 'dark'}])[0]['mode'], 'dark')
        with self.assertRaises(ValueError):
            clean_assets([{'name': 'Logo', 'url': '/l.svg', 'mode': 'sepia'}])

    def test_contrast_follows_the_supported_modes(self):
        colors = clean_colors(make_identity()['colors'], 'both')

        self.assertEqual({r['mode'] for r in contrast_report(colors, 'AA', 'light')}, {'light'})
        self.assertEqual({r['mode'] for r in contrast_report(colors, 'AA', 'dark')}, {'dark'})
        self.assertEqual({r['mode'] for r in contrast_report(colors, 'AA', 'both')}, {'light', 'dark'})


class ThemeModeGeneratorTests(unittest.TestCase):
    def css(self, **overrides):
        return design_files(make_identity(**overrides))['identity/tokens.css']

    def test_system_default_follows_prefers_color_scheme(self):
        css = self.css(default_mode='system')

        self.assertIn('color-scheme: light;', css)
        self.assertIn('@media (prefers-color-scheme: dark)', css)
        self.assertIn(':root:not(.light):not([data-theme="light"])', css)
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn(':root[data-theme="light"]', css)

    def test_light_default_ignores_the_system_and_needs_data_theme_for_dark(self):
        css = self.css(default_mode='light')

        self.assertNotIn('prefers-color-scheme', css)
        self.assertIn(':root {\n  color-scheme: light;\n  --background: #ffffff;', css)
        self.assertIn('.dark, :root[data-theme="dark"] {\n  color-scheme: dark;', css)
        self.assertIn('--brand-primary: #6b9dff;', css)

    def test_dark_default_puts_dark_values_on_root(self):
        css = self.css(default_mode='dark')

        self.assertNotIn('prefers-color-scheme', css)
        self.assertIn(':root {\n  color-scheme: dark;\n  --background: #0b0d12;', css)
        self.assertIn('.light, :root[data-theme="light"] {\n  color-scheme: light;', css)

    def test_dark_only_identity_has_a_single_dark_root(self):
        css = self.css(theme_modes='dark', colors=DARK_ONLY)

        self.assertIn('color-scheme: dark;', css)
        self.assertIn('--brand-text: #eeeeee;', css)
        self.assertIn('.dark, :root[data-theme="dark"]', css)
        self.assertNotIn('prefers-color-scheme', css)
        self.assertNotIn('--brand-text: ;', css)

    def test_light_only_identity_declares_a_light_color_scheme(self):
        css = self.css(theme_modes='light', colors=LIGHT_ONLY)

        self.assertIn('color-scheme: light;', css)
        self.assertNotIn('#eeeeee', css)

    def test_dark_shadows_override_only_in_dark_mode(self):
        css = self.css(default_mode='light', shadows_dark={'card': '0 1px 3px rgba(0,0,0,0.8)'})

        self.assertIn('--brand-shadow-card: 0 1px 3px rgba(0,0,0,0.2);', css)
        self.assertIn('--brand-shadow-card: 0 1px 3px rgba(0,0,0,0.8);', css)
        self.assertLess(css.index('rgba(0,0,0,0.2)'), css.index('rgba(0,0,0,0.8)'))

    def test_dark_only_shadow_names_still_reach_tailwind(self):
        identity = make_identity(shadows={}, shadows_dark={'glow': '0 0 8px #fff'})
        files = design_files(identity)

        self.assertIn('--shadow-elevation-glow: var(--shadow-glow);', files['identity/tailwind.theme.css'])
        self.assertIn('"elevation-glow"', files['identity/tailwind.theme.ts'])

    def test_tailwind_dark_variant_follows_data_theme_only_when_toggled(self):
        variant = '@custom-variant dark (&:where(.dark, .dark *));'

        self.assertIn(variant, design_files(make_identity(default_mode='system'))['identity/tailwind.theme.css'])
        self.assertIn(variant, design_files(make_identity(default_mode='light'))['identity/tailwind.theme.css'])
        self.assertNotIn('@custom-variant', design_files(make_identity(theme_modes='light', colors=LIGHT_ONLY))['identity/tailwind.theme.css'])

    def test_tokens_ts_lists_the_modes_and_only_the_supported_colours(self):
        both = design_files()['identity/tokens.ts']
        dark_only = design_files(make_identity(theme_modes='dark', colors=DARK_ONLY))['identity/tokens.ts']

        self.assertIn('"modes": "both"', both)
        self.assertIn('"defaultMode": "system"', both)
        self.assertIn('"modes": "dark"', dark_only)
        self.assertIn('"light": {}', dark_only)
        self.assertIn('"text": "#eeeeee"', dark_only)

    def test_asset_modes_reach_the_manifest_and_the_styleguide(self):
        assets = [
            {'name': 'Logo on light', 'kind': 'logo', 'mode': 'light', 'url': '/l.svg', 'usage': ''},
            {'name': 'Logo on dark', 'kind': 'logo', 'mode': 'dark', 'url': '/d.svg', 'usage': ''},
        ]
        files = design_files(make_identity(assets=assets))

        self.assertIn('"mode": "dark"', files['identity/assets.ts'])
        self.assertIn('| Logo on dark | logo | dark |', files['identity/STYLEGUIDE.md'])
        self.assertIn('Use the `light` variant on light backgrounds', files['identity/STYLEGUIDE.md'])

    def test_assets_without_a_mode_are_treated_as_any(self):
        assets = [{'name': 'Logo', 'kind': 'logo', 'url': '/l.svg', 'usage': ''}]

        self.assertIn('| Logo | logo | any |', design_files(make_identity(assets=assets))['identity/STYLEGUIDE.md'])

    def test_styleguide_states_the_themes_and_only_checks_supported_modes(self):
        both = design_files(make_identity(default_mode='dark'))['identity/STYLEGUIDE.md']
        dark_only = design_files(make_identity(theme_modes='dark', colors=DARK_ONLY))['identity/STYLEGUIDE.md']

        self.assertIn('Modes: **Light and dark**', both)
        self.assertIn('Default: dark', both)
        self.assertIn('data-theme="dark"', both)
        self.assertIn('both light and dark mode', both)
        self.assertIn('Modes: **Dark only**', dark_only)
        self.assertNotIn('data-theme', dark_only)
        self.assertNotIn('| light |', dark_only)
        self.assertIn('| dark | text on background', dark_only)
        self.assertIn('| Text | text | - | `#eeeeee` |', dark_only)


class SkeletonIdentityTests(unittest.TestCase):
    def test_styleguide_is_only_in_the_skeleton_when_the_project_has_an_identity(self):
        with_identity = design_files(target='skeleton')
        without = {item['path'] for item in generate_files(make_spec(), 'skeleton')}

        self.assertIn('identity/STYLEGUIDE.md', with_identity)
        self.assertIn('identity/STYLEGUIDE.md', with_identity['README.md'])
        self.assertNotIn('identity/STYLEGUIDE.md', without)
