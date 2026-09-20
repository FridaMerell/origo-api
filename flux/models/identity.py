"""Visual identities: shared, user-owned brand profiles that projects can opt in to."""

from decimal import Decimal

from django.conf import settings
from django.db import models


def default_font_weights():
    return [400, 600, 700]


def default_radii():
    return {"sm": 4, "md": 8, "lg": 16}


class VisualProfile(models.Model):
    class AccessibilityTarget(models.TextChoices):
        AA = "AA", "WCAG AA"
        AAA = "AAA", "WCAG AAA"

    class ThemeModes(models.TextChoices):
        LIGHT = "light", "Light only"
        DARK = "dark", "Dark only"
        BOTH = "both", "Light and dark"

    class DefaultMode(models.TextChoices):
        SYSTEM = "system", "Follow the system"
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flux_identities")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    brand_name = models.CharField(max_length=120, blank=True)
    tagline = models.CharField(max_length=255, blank=True)
    tone = models.TextField(blank=True, help_text="Tone of voice for copy.")

    theme_modes = models.CharField(max_length=5, choices=ThemeModes.choices, default=ThemeModes.BOTH)
    default_mode = models.CharField(
        max_length=6, choices=DefaultMode.choices, default=DefaultMode.SYSTEM,
        help_text="Which theme applies before the user chooses, when both exist.",
    )
    colors = models.JSONField(
        default=list, blank=True,
        help_text="[{name, role, light, dark}] with #RRGGBB values; which values are required follows theme_modes.",
    )

    heading_font = models.CharField(max_length=120, blank=True)
    body_font = models.CharField(max_length=120, blank=True)
    mono_font = models.CharField(max_length=120, blank=True)
    font_import_url = models.CharField(max_length=500, blank=True, help_text="Stylesheet that loads the fonts.")
    font_weights = models.JSONField(default=default_font_weights, blank=True)
    base_font_size = models.PositiveSmallIntegerField(default=16)
    type_scale_ratio = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("1.25"))

    spacing_unit = models.PositiveSmallIntegerField(default=4)
    radii = models.JSONField(default=default_radii, blank=True)
    shadows = models.JSONField(default=dict, blank=True)
    shadows_dark = models.JSONField(default=dict, blank=True, help_text="Overrides of shadows in dark mode.")

    assets = models.JSONField(
        default=list, blank=True,
        help_text="[{name, kind, mode (any/light/dark), url, usage}] logos, icons, favicons.",
    )
    logo_rules = models.TextField(blank=True, help_text="Minimum size, clear space, allowed backgrounds.")
    icon_library = models.CharField(max_length=60, blank=True)
    icon_style = models.CharField(max_length=60, blank=True)

    accessibility_target = models.CharField(
        max_length=3, choices=AccessibilityTarget.choices, default=AccessibilityTarget.AA
    )
    guidelines = models.TextField(blank=True, help_text="Free-form markdown: imagery, do and don't, component rules.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="flux_identity_unique_name_per_owner")]

    def __str__(self):
        return self.name
