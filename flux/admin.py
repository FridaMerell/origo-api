from django.contrib import admin

from flux.models import Project, Task


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'updated_at']
    filter_horizontal = ['members']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'parent', 'priority', 'due_date', 'created_at', 'updated_at']
    list_filter = ['project', 'priority']
    filter_horizontal = ['requirements', 'assignees']
