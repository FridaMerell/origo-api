"""Income serialization."""

from rest_framework import serializers

from verso.models import Income


class IncomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Income
        fields = ["id", "house", "booking", "amount", "description", "date_received", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        if not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        booking = attrs.get("booking", getattr(self.instance, "booking", None))
        if booking is not None and booking.house_id != house.pk:
            raise serializers.ValidationError({"booking": "The booking must belong to the selected house."})
        return attrs
