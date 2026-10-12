from django.db.models.functions import Lower
from rest_framework import serializers

from opus.access import can_access_work, can_edit_lexical_entry, visible_entry_filter
from opus.models import Glossary, LexicalEntry, LexicalForm, LexicalSynonym, TextUnit

MAX_CONNOTATIONS = 20
MAX_CONNOTATION_LENGTH = 50


def synonym_payload(entry):
    """An entry's synonyms as plain dicts, with ``target_lemma`` for a synonym that is a word of its own.

    Uses prefetched ``synonyms`` when present. An entry whose synonyms were saved as a list in
    ``inflection_data`` before they had a table keeps showing them until it is saved again.
    """

    rows = list(entry.synonyms.all())
    if rows:
        return [
            {
                "id": row.id,
                "text": row.text,
                "target": row.target_id,
                "target_lemma": row.target.lemma if row.target_id else None,
            }
            for row in rows
        ]
    legacy = entry.inflection_data.get("synonyms") if isinstance(entry.inflection_data, dict) else None
    if not isinstance(legacy, list):
        return []
    return [
        {"id": None, "text": text, "target": None, "target_lemma": None}
        for text in legacy
        if isinstance(text, str) and text.strip()
    ]


class LexicalFormSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()

    class Meta:
        model = LexicalForm
        fields = [
            "id", "entry", "form", "kind", "inflection", *LexicalForm.GRAMMAR_FIELDS, "is_uncertain",
            "unit", "source", "created_at", "updated_at",
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


class LexicalSynonymSerializer(serializers.ModelSerializer):
    """Input for one synonym of an entry; ``target`` optionally names another word of the lexicon."""

    class Meta:
        model = LexicalSynonym
        fields = ["id", "text", "target"]
        read_only_fields = ["id"]


class LexicalEntrySerializer(serializers.ModelSerializer):
    glossaries = serializers.SerializerMethodField()
    forms = LexicalFormSerializer(many=True, read_only=True)
    in_quiz = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    # Written as a whole list that replaces the entry's synonyms; read through ``synonym_payload``.
    synonyms = LexicalSynonymSerializer(many=True, required=False, write_only=True)

    class Meta:
        model = LexicalEntry
        fields = [
            "id", "lemma", "language", "part_of_speech", "gender", "inflection_data", "translation",
            "definition", "connotations", "connotation_note", "synonyms", "owner", "glossaries", "forms",
            "in_quiz", "can_edit",
        ]
        read_only_fields = ["id", "owner"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["synonyms"] = synonym_payload(instance)
        return data

    def get_can_edit(self, obj):
        """Whether the requesting user may change the word: their own, or an unowned one they may claim."""

        allowed = getattr(obj, "request_can_edit", None)
        return can_edit_lexical_entry(obj, self.context["request"].user) if allowed is None else allowed

    def get_in_quiz(self, obj):
        """Whether the requesting user has marked the word for their quizzes."""

        marked = getattr(obj, "request_in_quiz", None)
        if marked is None:
            return obj.quiz_users.filter(pk=self.context["request"].user.pk).exists()
        return marked

    def validate_connotations(self, value):
        if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
            raise serializers.ValidationError("Connotations must be a list of strings.")
        tags, seen = [], set()
        for tag in (tag.strip() for tag in value):
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
        if len(tags) > MAX_CONNOTATIONS:
            raise serializers.ValidationError(f"At most {MAX_CONNOTATIONS} connotations.")
        if any(len(tag) > MAX_CONNOTATION_LENGTH for tag in tags):
            raise serializers.ValidationError(f"A connotation is at most {MAX_CONNOTATION_LENGTH} characters.")
        return tags

    def validate_synonyms(self, items):
        """Each synonym once, and linked only to a word the user can see other than the entry itself."""

        result, seen = [], set()
        for item in items:
            text = item["text"].strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                result.append({"text": text, "target": item.get("target")})
        target_ids = {item["target"].pk for item in result if item["target"] is not None}
        if self.instance is not None and self.instance.pk in target_ids:
            raise serializers.ValidationError("A word cannot be its own synonym.")
        if target_ids:
            user = self.context["request"].user
            visible = LexicalEntry.objects.filter(visible_entry_filter(user), pk__in=target_ids).count()
            if visible != len(target_ids):
                raise serializers.ValidationError("A synonym is linked to a word that does not exist.")
        return result

    def create(self, validated_data):
        synonyms = validated_data.pop("synonyms", None)
        entry = super().create(validated_data)
        if synonyms is not None:
            self._replace_synonyms(entry, synonyms)
        return entry

    def update(self, instance, validated_data):
        synonyms = validated_data.pop("synonyms", None)
        entry = super().update(instance, validated_data)
        if synonyms is not None:
            self._replace_synonyms(entry, synonyms)
        return entry

    @staticmethod
    def _replace_synonyms(entry, items):
        """Make ``items`` the entry's synonyms.

        A synonym without a link is linked to the owner's one word in the same language that has it
        as its lemma, when there is exactly one.
        """

        texts = [item["text"].lower() for item in items if item["target"] is None]
        lemma_owners = {}
        if texts and entry.owner_id is not None:
            candidates = (
                LexicalEntry.objects.filter(owner_id=entry.owner_id, language__iexact=entry.language)
                .exclude(pk=entry.pk)
                .annotate(lemma_lower=Lower("lemma"))
                .filter(lemma_lower__in=texts)
            )
            for candidate in candidates:
                lemma_owners.setdefault(candidate.lemma_lower, []).append(candidate)

        LexicalSynonym.objects.filter(entry=entry).delete()
        rows = []
        for item in items:
            target = item["target"]
            if target is None:
                matches = lemma_owners.get(item["text"].lower(), [])
                target = matches[0] if len(matches) == 1 else None
            rows.append(LexicalSynonym(entry=entry, text=item["text"], target=target))
        LexicalSynonym.objects.bulk_create(rows)

        # Synonyms now live in their own rows, so the older list is dropped.
        if isinstance(entry.inflection_data, dict) and "synonyms" in entry.inflection_data:
            entry.inflection_data = {key: value for key, value in entry.inflection_data.items() if key != "synonyms"}
            entry.save(update_fields=["inflection_data"])

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
    """One glossary. Its words are read a page at a time from ``/lexical-entries/?glossaries=<id>``."""

    # How many of its words the requesting user has marked for quizzes.
    marked_count = serializers.SerializerMethodField()

    class Meta(GlossarySerializer.Meta):
        fields = GlossarySerializer.Meta.fields + ["marked_count"]

    def get_marked_count(self, obj):
        count = getattr(obj, "marked_count", None)
        if count is None:
            return obj.entries.filter(quiz_users=self.context["request"].user).count()
        return count


class GlossaryEntrySerializer(serializers.Serializer):
    """Input for adding an existing lexical entry to a glossary."""

    lexical_entry = serializers.PrimaryKeyRelatedField(queryset=LexicalEntry.objects.all())


class GlossaryQuizSerializer(serializers.Serializer):
    """Query parameters for drawing a random set of quiz words from a glossary."""

    count = serializers.IntegerField(min_value=1, max_value=200, default=20)
    # Only among the words the user has marked for quizzes.
    marked = serializers.BooleanField(default=False)


class LanguageQuizSerializer(GlossaryQuizSerializer):
    """Query parameters for drawing a random set of quiz words in one language from the user's own words."""

    language = serializers.CharField(max_length=16)
