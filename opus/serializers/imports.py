from rest_framework import serializers


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        error_messages={
            "required": "A document file is required.",
            "invalid": "The submitted file is invalid.",
            "empty": "The uploaded document is empty.",
        }
    )
