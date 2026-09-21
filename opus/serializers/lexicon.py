from rest_framework import serializers

from opus.models import LexicalEntry


class LexicalEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LexicalEntry
        fields = ["id", "lemma", "language", "part_of_speech", "gender", "inflection_data"]
        read_only_fields = ["id"]
