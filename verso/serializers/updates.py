"""House-update serialization."""

from rest_framework import serializers

from verso.models import VersoUpdate


class VersoUpdateSerializer(serializers.ModelSerializer):
    by = serializers.StringRelatedField(source="author.username", read_only=True)
    author = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = VersoUpdate
        fields = ["id", "venture", "task", "by", "author", "title", "content", "created_at", "updated_at", "files", "house"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        if house is not None and not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate_venture(self, venture):
        if venture is not None and (venture.house_id is None or not venture.house.members.filter(pk=self.context["request"].user.pk).exists()):
            raise serializers.ValidationError("You must be a member of this venture's house.")
        return venture

    def validate_task(self, task):
        if task is None:
            return task
        venture = task.venture
        if venture.house_id is None or not venture.house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this task's venture house.")
        return task

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        task = attrs.get("task", getattr(self.instance, "task", None))
        related_houses = [value for value in (house, venture.house if venture is not None else None, task.venture.house if task is not None else None) if value is not None]
        if not related_houses:
            raise serializers.ValidationError("An update must belong to a house, venture, or task.")
        if any(value.pk != related_houses[0].pk for value in related_houses[1:]):
            raise serializers.ValidationError("The house, venture, and task must belong to the same house.")
        return attrs
