from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Alignment, AlignmentGroup, AlignmentMember, AlignmentSet, AlignmentVersion


class AlignmentSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlignmentSet
        fields = [
            "id", "work", "owner", "name", "is_public", "status", "source_version", "target_version",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)

    def validate_work(self, work):
        if not can_access_work(work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private work you do not own.")
        return work

    def validate_source_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version

    def validate_target_version(self, version):
        return self.validate_source_version(version)

    def validate(self, attrs):
        source = attrs.get("source_version") or getattr(self.instance, "source_version", None)
        target = attrs.get("target_version") or getattr(self.instance, "target_version", None)
        if source is not None and target is not None and source.pk == target.pk:
            raise serializers.ValidationError("Source and target editions must be different.")
        work = attrs.get("work") or getattr(self.instance, "work", None)
        for edition in (source, target):
            if work is not None and edition is not None and edition.work_id != work.pk:
                raise serializers.ValidationError("All editions must belong to the alignment set's work.")
        return attrs


class AlignmentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlignmentVersion
        fields = ["id", "alignment_set", "text_version", "display_order", "label", "role"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        alignment_set = attrs.get("alignment_set") or getattr(self.instance, "alignment_set", None)
        version = attrs.get("text_version") or getattr(self.instance, "text_version", None)
        if alignment_set and version:
            if alignment_set.work_id and version.work_id != alignment_set.work_id:
                raise serializers.ValidationError({"text_version": "Must belong to the alignment set's work."})
            if not can_access_work(version.work, self.context["request"].user):
                raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return attrs


class AlignmentGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlignmentGroup
        fields = ["id", "alignment_set", "sequence", "label"]
        read_only_fields = ["id"]

    def validate_alignment_set(self, alignment_set):
        if alignment_set.work_id and not can_access_work(alignment_set.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use an alignment set for a private work you do not own.")
        return alignment_set


class AlignmentMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlignmentMember
        fields = ["id", "group", "alignment_version", "start_unit", "end_unit", "status"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        group = attrs.get("group") or getattr(self.instance, "group", None)
        alignment_version = attrs.get("alignment_version") or getattr(self.instance, "alignment_version", None)
        if group and group.alignment_set.work_id and not can_access_work(
            group.alignment_set.work, self.context["request"].user
        ):
            raise serializers.ValidationError("You cannot use an alignment group for a private work you do not own.")
        if group and alignment_version and group.alignment_set_id != alignment_version.alignment_set_id:
            raise serializers.ValidationError("Group and alignment edition must belong to the same alignment set.")
        for key in ("start_unit", "end_unit"):
            unit = attrs.get(key, getattr(self.instance, key, None))
            if unit is not None and alignment_version is not None and unit.version_id != alignment_version.text_version_id:
                raise serializers.ValidationError({key: "Must belong to the alignment member's edition."})
        return attrs


class AlignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alignment
        fields = [
            "id", "alignment_set", "source_start", "source_end", "target_start", "target_end",
            "alignment_type", "confidence", "source_unit", "target_unit", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_alignment_set(self, alignment_set):
        user = self.context["request"].user
        work = alignment_set.work
        if work is None and alignment_set.source_version is not None:
            work = alignment_set.source_version.work
        if work is None or not can_access_work(work, user):
            raise serializers.ValidationError("You cannot use an alignment set for a private work you do not own.")
        return alignment_set

    def validate(self, attrs):
        alignment_set = attrs.get("alignment_set") or getattr(self.instance, "alignment_set", None)
        source_unit = attrs.get("source_unit", getattr(self.instance, "source_unit", None))
        target_unit = attrs.get("target_unit", getattr(self.instance, "target_unit", None))
        if alignment_set is not None:
            if (
                source_unit is not None
                and alignment_set.source_version_id is not None
                and source_unit.version_id != alignment_set.source_version_id
            ):
                raise serializers.ValidationError({"source_unit": "Must belong to the alignment set's source edition."})
            if (
                target_unit is not None
                and alignment_set.target_version_id is not None
                and target_unit.version_id != alignment_set.target_version_id
            ):
                raise serializers.ValidationError({"target_unit": "Must belong to the alignment set's target edition."})
        return attrs
