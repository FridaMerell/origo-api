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
            "tasks",
            "created_at",
            "updated_at",
            "finished_tasks_count",
            "total_tasks_count",
            "total_spent",
        ]

    def validate_house(self, house):
        request = self.context["request"]
        if house is None or not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        if house is None:
            raise serializers.ValidationError("A venture must belong to a house.")
        return attrs

    def get_finished_tasks_count(self, obj):
        if hasattr(obj, 'finished_tasks_count'):
            return obj.finished_tasks_count
        return obj.tasks.filter(completed=True).count()

    def get_total_tasks_count(self, obj):
        if hasattr(obj, 'total_tasks_count'):
            return obj.total_tasks_count
        return obj.tasks.count()

    def get_total_spent(self, obj):
        if hasattr(obj, 'total_spent'):
            return obj.total_spent or 0.00
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

    def validate_venture(self, venture):
        request = self.context["request"]
        if (
            venture.house_id is None
            or not venture.house.members.filter(pk=request.user.pk).exists()
        ):
            raise serializers.ValidationError(
                "You must be a member of this venture's house."
            )
        return venture


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

    def validate_house(self, house):
        request = self.context["request"]
        if house is not None and not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate_venture(self, venture):
        request = self.context["request"]
        if venture is not None and (
            venture.house_id is None
            or not venture.house.members.filter(pk=request.user.pk).exists()
        ):
            raise serializers.ValidationError(
                "You must be a member of this venture's house."
            )
        return venture

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        if house is None and venture is None:
            raise serializers.ValidationError(
                "An expense must belong to a house or venture."
            )
        if house is not None and venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError(
                {"venture": "The venture must belong to the selected house."}
            )
        return attrs


class VersoUpdateSerializer(serializers.ModelSerializer):
    by = serializers.StringRelatedField(source="author.username", read_only=True)
    author = serializers.PrimaryKeyRelatedField(read_only=True)
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
            "house"
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        request = self.context["request"]
        if house is not None and not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate_venture(self, venture):
        request = self.context["request"]
        if venture is not None and (
            venture.house_id is None
            or not venture.house.members.filter(pk=request.user.pk).exists()
        ):
            raise serializers.ValidationError(
                "You must be a member of this venture's house."
            )
        return venture

    def validate_task(self, task):
        request = self.context["request"]
        venture = task.venture
        if venture.house_id is None or not venture.house.members.filter(
            pk=request.user.pk
        ).exists():
            raise serializers.ValidationError(
                "You must be a member of this task's venture house."
            )
        return task

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        task = attrs.get("task", getattr(self.instance, "task", None))
        related_houses = [
            related_house
            for related_house in (
                house,
                venture.house if venture is not None else None,
                task.venture.house if task is not None else None,
            )
            if related_house is not None
        ]
        if not related_houses:
            raise serializers.ValidationError(
                "An update must belong to a house, venture, or task."
            )
        if any(
            related_house.pk != related_houses[0].pk
            for related_house in related_houses[1:]
        ):
            raise serializers.ValidationError(
                "The house, venture, and task must belong to the same house."
            )
        return attrs
