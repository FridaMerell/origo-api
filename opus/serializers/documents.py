from django.db.models import Max
from rest_framework import serializers

from opus.access import can_access_work
from opus.models import AlignmentVersion, Bookmark, Excerpt, ReadingProgress, TextUnit


class ReadingProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingProgress
        fields = ["id", "user", "work", "position", "character_index", "updated_at"]
        read_only_fields = ["id", "user", "updated_at"]

    def validate_work(self, work):
        if not can_access_work(work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return work


# Longest piece of the bookmarked (or currently read) text returned with it.
BOOKMARK_EXCERPT_LENGTH = 280


def _excerpt(content):
    return content if len(content) <= BOOKMARK_EXCERPT_LENGTH else f"{content[:BOOKMARK_EXCERPT_LENGTH]}…"


class ReadingProgressOverviewSerializer(ReadingProgressSerializer):
    """A reading position with where it points, for a "continue reading" overview.

    A position is a paragraph position in one edition's numbering. Like the parallel grid
    (``Grid.row_at_position``), the reference is the first edition of the reader's own
    alignment set for the work, falling back to the work's first edition.
    """

    work_title = serializers.CharField(source="work.title", read_only=True)
    edition = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    percent = serializers.SerializerMethodField()

    class Meta(ReadingProgressSerializer.Meta):
        fields = ReadingProgressSerializer.Meta.fields + ["work_title", "edition", "unit", "percent"]

    def _state(self, obj):
        """The reference edition, the paragraph at the position and the edition's last position."""

        cache = self.__dict__.setdefault("_reading_states", {})
        if obj.pk in cache:
            return cache[obj.pk]
        version = (
            AlignmentVersion.objects.filter(alignment_set__work_id=obj.work_id, alignment_set__owner_id=obj.user_id)
            .select_related("text_version")
            .order_by("alignment_set__name", "alignment_set_id", "display_order", "id")
            .first()
        )
        edition = version.text_version if version else obj.work.editions.order_by("title", "id").first()
        unit = last_position = None
        if edition is not None:
            paragraphs = TextUnit.objects.filter(version=edition, kind=TextUnit.Kind.PARAGRAPH)
            unit = (
                paragraphs.filter(position__gte=obj.position).select_related("parent").order_by("position", "id").first()
            )
            last_position = paragraphs.aggregate(last=Max("position"))["last"]
        cache[obj.pk] = (edition, unit, last_position)
        return cache[obj.pk]

    def get_edition(self, obj):
        edition = self._state(obj)[0]
        return {"id": edition.id, "title": edition.title} if edition else None

    def get_unit(self, obj):
        """The paragraph at the position, or ``None`` when the position is past the end."""

        unit = self._state(obj)[1]
        if unit is None:
            return None
        chapter = unit.parent if unit.parent and unit.parent.kind == TextUnit.Kind.CHAPTER else None
        return {
            "id": unit.id,
            "excerpt": _excerpt(unit.content),
            "chapter": {"id": chapter.id, "label": chapter.label} if chapter else None,
        }

    def get_percent(self, obj):
        _, unit, last_position = self._state(obj)
        if not last_position:
            return 0
        if unit is None:
            return 100
        return max(0, min(100, round(obj.position / last_position * 100)))


class BookmarkSerializer(serializers.ModelSerializer):
    # Read-only context, so a list of bookmarks can be shown without fetching each unit.
    work = serializers.SerializerMethodField()
    edition_title = serializers.CharField(source="version.title", read_only=True)
    chapter = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()

    class Meta:
        model = Bookmark
        fields = [
            "id", "user", "version", "unit", "offset", "title", "note", "created_at",
            "work", "edition_title", "chapter", "excerpt",
        ]
        read_only_fields = ["id", "user", "created_at"]

    def get_work(self, obj):
        return {"id": obj.version.work_id, "title": obj.version.work.title}

    def get_chapter(self, obj):
        parent = obj.unit.parent
        if parent is None or parent.kind != TextUnit.Kind.CHAPTER:
            return None
        return {"id": parent.id, "label": parent.label}

    def get_excerpt(self, obj):
        return _excerpt(obj.unit.content)

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version

    def validate(self, attrs):
        version = attrs.get("version", getattr(self.instance, "version", None))
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        if version is not None and unit is not None and unit.version_id != version.pk:
            raise serializers.ValidationError({"unit": "Must belong to the selected edition."})
        return attrs


class ExcerptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Excerpt
        fields = [
            "id", "user", "version", "unit", "start_offset", "end_offset", "text_snapshot",
            "title", "note", "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version

    def validate(self, attrs):
        version = attrs.get("version", getattr(self.instance, "version", None))
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        if version is not None and unit is not None and unit.version_id != version.pk:
            raise serializers.ValidationError({"unit": "Must belong to the selected edition."})
        return attrs
