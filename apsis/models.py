from django.db import models
from django.conf import settings

class Post(models.Model):
    files = models.JSONField(blank=True, default=list)  # Store file metadata as a list of dictionaries
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    geolocation = models.CharField(max_length=255, blank=True)
    content = models.TextField()
    name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return ", ".join(file.get('name', '?') for file in self.files) if self.files else "No files"