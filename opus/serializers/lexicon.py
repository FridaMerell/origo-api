from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Glossary, LexicalEntry, LexicalForm, TextUnit


class LexicalFormSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()

    class Meta:
        model = LexicalForm
        fields = [
            "id", "entry", "form", "kind", "inflection", "is_uncertain", "unit", "source",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_source(self, obj):
        """Where the form was found, for linking to it; null when unset or in a private work of someone else."""

        unit = obj.unit
        if unit is None or not can_access_work(unit.version.work, self.context["request"].user):
            return None
        parent = unit.parent
        return {
            "work": {"id": unit.version.work_id, "title": unit.version.work.title},
            "edition_title": unit.version.title,
            "chapter": (
                {"id": parent.id, "label": parent.label}
                if parent is not None and parent.kind == TextUnit.Kind.CHAPTER
                else None
            ),
        }

    def validate_unit(self, unit):
        if unit is not None and not can_access_work(unit.version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot link a form to a private work you do not own.")
        return unit


class LexicalEntrySerializer(serializers.ModelSerializer):
    glossaries = serializers.SerializerMethodField()
    forms = LexicalFormSerializer(many=True, read_only=True)

    class Meta:
        model = LexicalEntry
        fields = [
            "id", "lemma", "language", "part_of_speech", "gender", "inflection_data", "translation",
            "definition", "owner", "glossaries", "forms",
        ]
        read_only_fields = ["id", "owner"]

    def get_glossaries(self, obj):
        """IDs of the requesting user's own glossaries that contain the entry."""

        glossaries = getattr(obj, "request_glossaries", None)
        if glossaries is None:
            glossaries = obj.glossaries.filter(owner=self.context["request"].user)
        return [glossary.id for glossary in glossaries]


class GlossarySerializer(serializers.ModelSerializer):
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = Glossary
        fields = [
            "id", "title", "description", "owner", "is_private", "entry_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]

    def get_entry_count(self, obj):
        count = getattr(obj, "entry_count", None)
        return obj.entries.count() if count is None else count


class GlossaryDetailSerializer(GlossarySerializer):
    entries = serializers.SerializerMethodField()

    class Meta(GlossarySerializer.Meta):
        fields = GlossarySerializer.Meta.fields + ["entries"]

    def get_entries(self, obj):
        return LexicalEntrySerializer(obj.entries.all(), many=True, context=self.context).data


class GlossaryEntrySerializer(serializers.Serializer):
    """Input for adding an existing lexical entry to a glossary."""

    lexical_entry = serializers.PrimaryKeyRelatedField(queryset=LexicalEntry.objects.all())


class GlossaryQuizSerializer(serializers.Serializer):
    """Query parameters for drawing a random set of quiz words from a glossary."""

    count = serializers.IntegerField(min_value=1, max_value=200, default=20)


class LanguageQuizSerializer(GlossaryQuizSerializer):
    """Query parameters for drawing a random set of quiz words in one language from the user's own words."""

    language = serializers.CharField(max_length=16)
