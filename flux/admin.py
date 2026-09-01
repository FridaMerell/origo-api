from django.contrib import admin

from flux.models import Milestone, Project, Task, Update
from origo.admin import site


@admin.register(Project, site=site)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'updated_at']
    filter_horizontal = ['members']


@admin.register(Milestone, site=site)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'target_date', 'created_at', 'updated_at']
    list_filter = ['project', 'status']


@admin.register(Task, site=site)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'project',
        'milestone',
        'parent',
        'priority',
        'status',
        'due_date',
        'recurrence',
        'recurrence_interval',
        'recurrence_end_date',
        'created_at',
        'updated_at',
    ]
    list_filter = ['project', 'priority', 'status', 'recurrence']
    filter_horizontal = ['requirements', 'assignees']


@admin.register(Update, site=site)
class FluxUpdateAdmin(admin.ModelAdmin):
    list_display = ['project', 'milestone', 'task', 'author', 'created_at']
    list_filter = ['project']
