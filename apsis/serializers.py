import rest_framework.serializers as serializers
import apsis.models as models


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Post
        fields = [
            'id',
            'files',
            'author',
            'geolocation',
            'content',
            'name',
            'created_at',
        ]
        read_only_fields = ['created_at']