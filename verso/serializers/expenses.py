"""Expense serialization."""

from rest_framework import serializers

from verso.models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = ["id", "venture", "amount", "description", "date_incurred", "created_at", "updated_at", "house"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        if house is not None and not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate_venture(self, venture):
        if venture is not None and (venture.house_id is None or not venture.house.members.filter(pk=self.context["request"].user.pk).exists()):
            raise serializers.ValidationError("You must be a member of this venture's house.")
        return venture

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        if house is None and venture is None:
            raise serializers.ValidationError("An expense must belong to a house or venture.")
        if house is not None and venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError({"venture": "The venture must belong to the selected house."})
        return attrs
