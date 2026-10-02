from rest_framework import serializers

from opus.services.importing import SEGMENT_SENTENCES, SEGMENTATIONS


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        error_messages={
            "required": "A document file is required.",
            "invalid": "The submitted file is invalid.",
            "empty": "The uploaded document is empty.",
        }
    )
    # One reading unit per sentence (prose) or per line (verse, drama).
    segmentation = serializers.ChoiceField(choices=SEGMENTATIONS, default=SEGMENT_SENTENCES)
    # A choice rather than a BooleanField: in multipart form data DRF reads an omitted boolean
    # as false, which would silently drop the front matter whenever a client leaves it out.
    front_matter = serializers.ChoiceField(choices=["keep", "skip"], default="keep")
    # The chapter's name when the file has no chapter headings of its own (default: file name).
    label = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    # append-document only: the chapter (id) the new chapters go in front of; empty = at the end.
    before = serializers.IntegerField(required=False, allow_null=True, default=None)

    def extract_options(self):
        """Keyword arguments for ``extract_document``."""

        return {
            "segmentation": self.validated_data["segmentation"],
            "keep_front_matter": self.validated_data["front_matter"] == "keep",
        }
