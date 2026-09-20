"""Visual identity serialization."""

from rest_framework import serializers

from flux.models import VisualProfile
from flux.services.scaffold import identity as rules


def _checked(function, value):
    try:
        return function(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc


class VisualProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisualProfile
        fields = [
            "id", "owner", "name", "description", "brand_name", "tagline", "tone",
            "theme_modes", "default_mode", "colors",
            "heading_font", "body_font", "mono_font", "font_import_url", "font_weights",
            "base_font_size", "type_scale_ratio", "spacing_unit", "radii", "shadows", "shadows_dark",
            "assets", "logo_rules", "icon_library", "icon_style", "accessibility_target",
            "guidelines", "created_at", "updated_at",
        ]
        read_only_fields = ["owner", "created_at", "updated_at"]

    def validate_name(self, value):
        owner = self.instance.owner if self.instance is not None else self.context["request"].user
        duplicates = VisualProfile.objects.filter(owner=owner, name=value)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("You already have an identity with this name.")
        return value

    def validate(self, attrs):
        current = self.instance
        modes = attrs.get("theme_modes", current.theme_modes if current else "both")
        colors = attrs.get("colors", current.colors if current else [])
        try:
            attrs["colors"] = rules.clean_colors(colors, modes)
        except ValueError as exc:
            raise serializers.ValidationError({"colors": str(exc)}) from exc
        return attrs

    def validate_heading_font(self, value):
        return _checked(lambda v: rules.clean_font_name(v, "heading_font"), value)

    def validate_body_font(self, value):
        return _checked(lambda v: rules.clean_font_name(v, "body_font"), value)

    def validate_mono_font(self, value):
        return _checked(lambda v: rules.clean_font_name(v, "mono_font"), value)

    def validate_font_import_url(self, value):
        return _checked(rules.clean_import_url, value)

    def validate_font_weights(self, value):
        return _checked(rules.clean_font_weights, value)

    def validate_radii(self, value):
        return _checked(rules.clean_radii, value)

    def validate_shadows(self, value):
        return _checked(rules.clean_shadows, value)

    def validate_shadows_dark(self, value):
        return _checked(rules.clean_shadows, value)

    def validate_assets(self, value):
        return _checked(rules.clean_assets, value)

    def validate_base_font_size(self, value):
        if not 8 <= value <= 32:
            raise serializers.ValidationError("base_font_size must be between 8 and 32 pixels.")
        return value

    def validate_type_scale_ratio(self, value):
        if not 1 <= value <= 2:
            raise serializers.ValidationError("type_scale_ratio must be between 1 and 2.")
        return value

    def validate_spacing_unit(self, value):
        if not 1 <= value <= 16:
            raise serializers.ValidationError("spacing_unit must be between 1 and 16 pixels.")
        return value
