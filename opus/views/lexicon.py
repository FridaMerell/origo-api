from rest_framework import permissions, viewsets

from opus.models import LexicalEntry
from opus.serializers import LexicalEntrySerializer


class LexicalEntryViewSet(viewsets.ModelViewSet):
    queryset = LexicalEntry.objects.all()
    serializer_class = LexicalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "language": ["exact"],
        "part_of_speech": ["exact"],
        "gender": ["exact"],
        "lemma": ["exact", "icontains"],
    }
