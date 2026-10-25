"""ResidentialHeating connection serialization. The token is write-only."""

from rest_framework import serializers

from verso.models import ResidentialHeating


class ResidentialHeatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResidentialHeating
        fields = ["id", "house", "base_url", "token", "device", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"token": {"write_only": True}}

    def validate_house(self, house):
        if not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house
