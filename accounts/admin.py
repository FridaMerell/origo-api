from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import Notification, User

admin.site.register(User, UserAdmin)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'domain', 'message', 'is_read', 'created_at', 'sent_by']
    list_filter = ['domain', 'is_read']
    search_fields = ['message', 'user__username', 'user__email']
