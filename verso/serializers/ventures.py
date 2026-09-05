"""Venture and venture-task serialization."""

from django.db import models
from rest_framework import serializers

from verso.models import Venture, VentureTask


class VentureSerializer(serializers.ModelSerializer):
    finished_tasks_count = serializers.SerializerMethodField()
    total_tasks_count = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()

    class Meta:
        model = Venture
        fields = ["id", "name", "description", "priority", "budget", "files", "created_at", "updated_at", "house", "tasks", "finished_tasks_count", "total_tasks_count", "total_spent"]
        read_only_fields = ["tasks", "created_at", "updated_at", "finished_tasks_count", "total_tasks_count", "total_spent"]

    def validate_house(self, house):
        if house is None or not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        if attrs.get("house", getattr(self.instance, "house", None)) is None:
            raise serializers.ValidationError("A venture must belong to a house.")
        return attrs

    def get_finished_tasks_count(self, obj):
        return obj.finished_tasks_count if hasattr(obj, "finished_tasks_count") else obj.tasks.filter(completed=True).count()

    def get_total_tasks_count(self, obj):
        return obj.total_tasks_count if hasattr(obj, "total_tasks_count") else obj.tasks.count()

    def get_total_spent(self, obj):
        return obj.total_spent or 0.00 if hasattr(obj, "total_spent") else obj.expenses.aggregate(total=models.Sum("amount"))["total"] or 0.00


class VentureTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = VentureTask
        fields = ["id", "venture", "name", "description", "completed", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_venture(self, venture):
        if venture.house_id is None or not venture.house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this venture's house.")
        return venture
