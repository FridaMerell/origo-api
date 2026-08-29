from django.shortcuts import render
import rest_framework.viewsets as viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
import apsis.models as models
import apsis.serializers as serializers
# Create your views here.

class PostViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = models.Post.objects.all()

