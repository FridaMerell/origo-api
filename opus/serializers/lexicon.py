from rest_framework import serializers

from opus.models import Glossary, LexicalEntry


class LexicalEntrySerializer(serializers.ModelSerializer):
    glossaries = serializers.SerializerMethodField()

    class Meta:
        model = LexicalEntry
        fields = [
            "id", "lemma", "language", "part_of_speech", "gender", "inflection_data", "definition",
            "owner", "glossaries",
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
