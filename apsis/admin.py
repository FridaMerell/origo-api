from django.contrib import admin

from apsis.models import Post
from origo.admin import site


@admin.register(Post, site=site)
class PostAdmin(admin.ModelAdmin):
    list_display = ['name', 'author', 'geolocation', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'content', 'geolocation', 'author__username']
