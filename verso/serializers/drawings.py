"""Drawing and drawing-page serialization."""

from rest_framework import serializers

from verso.models import Drawing, DrawingPage

ELEMENT_TYPES = {"line", "polyline", "polygon", "rect", "ellipse", "dimension", "text", "note"}
# Square millimeters per square unit, to report areas in square meters.
_UNIT_TO_MM = {"mm": 1, "cm": 10, "m": 1000}


def _shape_area(element):
    """Area of a rect or polygon element in square drawing units, else 0."""
    try:
        if element["type"] == "rect":
            return abs(float(element["width"]) * float(element["height"]))
        if element["type"] == "polygon":
            points = [(float(x), float(y)) for x, y in element["points"]]
            twice = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
            return abs(twice) / 2
    except (KeyError, TypeError, ValueError):
        pass
    return 0


def page_area(elements, unit):
    """Net area in m2: shapes with role "surface" minus shapes with role "opening"."""
    factor = _UNIT_TO_MM[unit] ** 2 / 1_000_000
    surface = sum(_shape_area(e) for e in elements if e.get("role") == "surface")
    opening = sum(_shape_area(e) for e in elements if e.get("role") == "opening")
    return {
        "surface_m2": round(surface * factor, 3),
        "openings_m2": round(opening * factor, 3),
        "net_m2": round((surface - opening) * factor, 3),
    }


class DrawingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Drawing
        fields = ["id", "house", "venture", "name", "description", "unit", "author", "pages", "created_at", "updated_at"]
        read_only_fields = ["author", "pages", "created_at", "updated_at"]

    def validate_house(self, house):
        if house is None or not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        if venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError({"venture": "The venture must belong to the same house."})
        return attrs

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)


class DrawingPageSerializer(serializers.ModelSerializer):
    area = serializers.SerializerMethodField()

    class Meta:
        model = DrawingPage
        fields = ["id", "drawing", "name", "order", "width", "height", "elements", "area", "created_at", "updated_at"]
        read_only_fields = ["area", "created_at", "updated_at"]

    def validate_drawing(self, drawing):
        if not drawing.house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this drawing's house.")
        return drawing

    def get_area(self, obj):
        return page_area(obj.elements, obj.drawing.unit)

    def validate_elements(self, elements):
        if not isinstance(elements, list):
            raise serializers.ValidationError("Elements must be a list.")
        for index, element in enumerate(elements):
            if not isinstance(element, dict) or element.get("type") not in ELEMENT_TYPES:
                raise serializers.ValidationError(f"Element {index} must be an object with a type in {sorted(ELEMENT_TYPES)}.")
        return elements
