"""Booking and checkout serialization."""

from rest_framework import serializers

from verso.models import Booking, BookingRequest, CheckOut


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ["id", "house", "visitor", "start_date", "end_date", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        if not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house


class CheckOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckOut
        fields = ["id", "booking", "check_out_time", "notes", "files"]
        read_only_fields = ["check_out_time"]

    def validate_booking(self, booking):
        if not booking.house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this booking's house.")
        return booking


class BookingRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingRequest
        fields = ["id", "house", "requester", "start_date", "end_date", "status", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        if not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house
