from django.contrib import admin

from flux.models import (
    Entity,
    Field,
    Integration,
    Milestone,
    Project,
    Relation,
    Resource,
    Role,
    RolePermission,
    Screen,
    SeedRow,
    StackProfile,
    Task,
    Update,
    VisualProfile,
)
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


@admin.register(Entity, site=site)
class EntityAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'created_at', 'updated_at']
    list_filter = ['project']


@admin.register(Field, site=site)
class FieldAdmin(admin.ModelAdmin):
    list_display = ['name', 'entity', 'type', 'nullable', 'unique', 'order']
    list_filter = ['entity__project', 'type']


@admin.register(Relation, site=site)
class RelationAdmin(admin.ModelAdmin):
    list_display = ['name', 'source', 'target', 'kind', 'on_delete', 'nullable']
    list_filter = ['source__project', 'kind']


@admin.register(StackProfile, site=site)
class StackProfileAdmin(admin.ModelAdmin):
    list_display = ['project', 'api_naming', 'auth_method', 'database']
    list_filter = ['database', 'auth_method']


@admin.register(Resource, site=site)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ['path', 'entity', 'ordering']
    list_filter = ['entity__project']


@admin.register(Role, site=site)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'project']
    list_filter = ['project']


@admin.register(RolePermission, site=site)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ['role', 'resource', 'operation', 'scope']
    list_filter = ['role__project', 'operation', 'scope']


@admin.register(Screen, site=site)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ['name', 'route', 'project', 'parent']
    list_filter = ['project']
    filter_horizontal = ['entities']


@admin.register(Integration, site=site)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ['name', 'kind', 'project']
    list_filter = ['project', 'kind']


@admin.register(SeedRow, site=site)
class SeedRowAdmin(admin.ModelAdmin):
    list_display = ['entity', 'order']
    list_filter = ['entity__project']


@admin.register(VisualProfile, site=site)
class VisualProfileAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'brand_name', 'accessibility_target', 'updated_at']
    list_filter = ['owner', 'accessibility_target']
    search_fields = ['name', 'brand_name']
