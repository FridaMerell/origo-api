"""Route planning serializers."""
from rest_framework import serializers

from tempus.models import Route, RouteStop, RouteSuggestionRun

from .common import validate_geojson


class RouteSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Route
        fields = [
            "id",
            "user",
            "name",
            "planned_date",
            "geometry",
            "corridor_metres",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def validate_geometry(self, value):
        return validate_geojson(value, "LineString")


class RouteStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteStop
        fields = ["id", "route", "sequence", "name", "location", "planned_at"]
        read_only_fields = ["id"]

    def validate_route(self, route):
        if route.user_id != self.context["request"].user.pk:
            raise serializers.ValidationError("The route does not belong to you.")
        return route

    def validate_location(self, value):
        return validate_geojson(value, "Point")


class SuggestedStopsQuerySerializer(serializers.Serializer):
    """Query params for the route ``suggested-stops`` action.

    All optional. ``taxon_id`` restricts scoring to a Dyntaxa taxon subtree
    (e.g. Aves = 4000104 for "bird stops"); ``since_days`` is the observation
    window used for scoring; ``notable_days`` is the cutoff for the "recent
    notable" list; ``max_detour_m`` drops stops that sit further than that off
    the route; ``num_stops`` caps the result; ``edge_buffer_m`` drops stops too
    close to either end of the route; ``min_gap_m`` is the minimum along-route
    spacing between stops. The last two default to fractions of route length.
    """

    taxon_id = serializers.IntegerField(min_value=1, required=False)
    since_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    notable_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    max_detour_m = serializers.FloatField(min_value=0, required=False)
    num_stops = serializers.IntegerField(min_value=1, max_value=25, required=False)
    # exclude stops within this many metres of either end of the route
    edge_buffer_m = serializers.FloatField(min_value=0, required=False)
    # minimum along-route spacing between kept stops
    min_gap_m = serializers.FloatField(min_value=0, required=False)


class RouteSuggestionRunSerializer(serializers.ModelSerializer):
    """Read-only view of a route's current rest-stop suggestion computation."""

    class Meta:
        model = RouteSuggestionRun
        fields = [
            "route",
            "status",
            "params",
            "result",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields
