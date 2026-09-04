from django.contrib import admin
import tempus.models
from origo.admin import site


@admin.register(tempus.models.SpeciesCategory, site=site)
class SpeciesCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "label", "taxon_id", "parent_category", "is_primary")
    list_filter = ("parent_category", "is_primary")
    list_select_related = ("parent_category",)
    search_fields = ("label", "parent_category__label", "taxon__scientific_name", "taxon__swedish_name")
    autocomplete_fields = ("parent_category", "taxon")


@admin.register(tempus.models.Species, site=site)
class SpeciesAdmin(admin.ModelAdmin):
    list_display = ("id", "swedish_name", "scientific_name")
    search_fields = ("swedish_name", "scientific_name")

@admin.register(tempus.models.Phenophase, site=site)
class PhenophaseAdmin(admin.ModelAdmin):
    list_display = ("id", "code")
    search_fields = ("code",)
    list_filter = ("code",)

@admin.register(tempus.models.Phenogram, site=site)
class PhenogramAdmin(admin.ModelAdmin):
    list_display = ("id", "species", "geo_area", "years", "peak_week", "sample_count", "computed_at")
    search_fields = ("species__swedish_name", "species__scientific_name", "geo_area__name")
    list_filter = ("geo_area", "years", "declustered")
    readonly_fields = ("computed_at",)

@admin.register(tempus.models.Source, site=site)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("id", "title")
    search_fields = ("title",)
    list_filter = ("title",)

@admin.register(tempus.models.GeoArea, site=site)
class GeoAreaAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "kind", "country_code")
    search_fields = ("name", "kind", "country_code")
    list_filter = ("kind", "country_code")

@admin.register(tempus.models.Checklist, site=site)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "description", "start_date", "end_date", "geo_area", "route", "created_at", "updated_at")
    search_fields = ("name", "user__username")
    list_filter = ("start_date", "end_date", "geo_area", "route")
    readonly_fields = ("created_at", "updated_at")


@admin.register(tempus.models.BirdnetDevice, site=site)
class BirdnetDeviceAdmin(admin.ModelAdmin):
    list_display = ("identifier", "name", "house", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "house")
    search_fields = ("identifier", "name")
    filter_horizontal = ("users",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(tempus.models.ChecklistItem, site=site)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = ("id", "checklist", "species", "sequence", "notes")
    readonly_fields = ("id",)

@admin.register(tempus.models.Observation, site=site)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ("id",  "species", "observed_at", "notes")
    readonly_fields = ("id",)