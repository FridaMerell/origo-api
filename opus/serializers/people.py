"""Serializers for people connected to literary works."""

from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Author, AuthorAlias, AuthorIdentifier, BibliographyEntry, WorkContributor


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = [
            "id", "name", "born", "died", "biography", "bibliography",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class AuthorAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorAlias
        fields = ["id", "author", "name", "language", "is_preferred"]
        read_only_fields = ["id"]


class AuthorIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorIdentifier
        fields = ["id", "author", "provider", "external_id", "external_url", "last_synced_at"]
        read_only_fields = ["id"]


class BibliographyEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = BibliographyEntry
        fields = [
            "id", "author", "work", "title", "year", "publisher", "language",
            "external_provider", "external_id", "source_url", "note", "sort_order",
        ]
        read_only_fields = ["id"]

    def validate_work(self, work):
        if work is not None and not can_access_work(work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private work you do not own.")
        return work


class WorkContributorSerializer(serializers.ModelSerializer):
    author = AuthorSerializer(read_only=True)
    author_id = serializers.PrimaryKeyRelatedField(
        source="author",
        queryset=Author.objects.all(),
        write_only=True,
    )

    class Meta:
        model = WorkContributor
        fields = ["id", "work", "author", "author_id", "role", "display_order"]
        read_only_fields = ["id"]

    def validate_work(self, work):
        if not can_access_work(work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private work you do not own.")
        return work
