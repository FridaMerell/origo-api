from rest_framework import serializers
from django.db import models
from verso.models import (
    Booking,
    BookingRequest,
    CheckOut,
    Expense,
    House,
    Venture,
    VentureTask,
    VersoUpdate,
)


class HouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = House
        fields = [
            "id",
            "name",
            "address",
            "members",
            "created_at",
            "updated_at",
            "lat",
            "lng",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            "id",
            "house",
            "visitor",
            "start_date",
            "end_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        request = self.context["request"]
        if not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house


class CheckOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckOut
        fields = [
            "id",
            "booking",
            "check_out_time",
            "notes",
            "files",
        ]
        read_only_fields = ["check_out_time"]

    def validate_booking(self, booking):
        request = self.context["request"]
        if not booking.house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError(
                "You must be a member of this booking's house."
            )
        return booking


class BookingRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingRequest
        fields = [
            "id",
            "house",
            "requester",
            "start_date",
            "end_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        request = self.context["request"]
        if not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house


class VentureSerializer(serializers.ModelSerializer):
    finished_tasks_count = serializers.SerializerMethodField()
    total_tasks_count = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()

    class Meta:
        model = Venture
        fields = [
            "id",
            "name",
            "description",
            "priority",
            "budget",
            "files",
            "created_at",
            "updated_at",
            "house",
            "tasks",
            "finished_tasks_count",
            "total_tasks_count",
            "total_spent",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "finished_tasks_count",
            "total_tasks_count",
            "total_spent",
        ]

    def get_finished_tasks_count(self, obj):
        return obj.tasks.filter(completed=True).count()

    def get_total_tasks_count(self, obj):
        return obj.tasks.count()

    def get_total_spent(self, obj):
        return obj.expenses.aggregate(total=models.Sum("amount"))["total"] or 0.00


class VentureTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = VentureTask
        fields = [
            "id",
            "venture",
            "name",
            "description",
            "completed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = [
            "id",
            "venture",
            "amount",
            "description",
            "date_incurred",
            "created_at",
            "updated_at",
            "house",
        ]
        read_only_fields = ["created_at", "updated_at"]


class VersoUpdateSerializer(serializers.ModelSerializer):
    by=author = serializers.StringRelatedField(source="author.username", read_only=True)
    class Meta:
        model = VersoUpdate
        fields = [
            "id",
            "venture",
            "task",
            "by",
            "author",
            "title",
            "content",
            "created_at",
            "updated_at",
            "files",
        ]
        read_only_fields = ["created_at", "updated_at"]
