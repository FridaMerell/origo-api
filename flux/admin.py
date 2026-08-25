from django.contrib import admin

from flux.models import Milestone, Project, Task, Update


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'updated_at']
    filter_horizontal = ['members']


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'target_date', 'created_at', 'updated_at']
    list_filter = ['project', 'status']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'milestone', 'parent', 'priority', 'due_date', 'created_at', 'updated_at']
    list_filter = ['project', 'priority']
    filter_horizontal = ['requirements', 'assignees']


@admin.register(Update)
class FluxUpdateAdmin(admin.ModelAdmin):
    list_display = ['project', 'milestone', 'task', 'author', 'created_at']
    list_filter = ['project']
