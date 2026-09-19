from django.contrib import admin
import tempus.models
from origo.admin import site
from tempus.services.locale_sources import SOURCES
from tempus.services.checklists import (
    link_observation_to_checklists,
    sync_observations_to_checklists,
)


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
    list_display = ("id", "user", "name", "description", "start_date", "end_date", "auto_add", "geo_area", "route", "created_at", "updated_at")
    search_fields = ("name", "user__username")
    list_filter = ("auto_add", "start_date", "end_date", "geo_area", "route")
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_observations_to_checklists(user=obj.user, checklist=obj)


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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_observations_to_checklists(user=obj.checklist.user, checklist=obj.checklist)

@admin.register(tempus.models.Observation, site=site)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ("id",  "species", "observed_at", "notes")
    readonly_fields = ("id",)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        link_observation_to_checklists(form.instance)

@admin.register(tempus.models.Locale, site=site)
class LocaleAdmin(admin.ModelAdmin):
    list_display=('id','name')
    readonly_fields=('id',)

@admin.register(tempus.models.LandCoverFetch, site=site)
class LandCoverFetchAdmin(admin.ModelAdmin):
    """Four raw JSON feature collections live on this model (``result``,
    ``hydrography``, ``place_names``, ``buildings``) and can each run to
    hundreds of features - shown as counts in the list, and tucked into a
    collapsed fieldset on the detail page so opening one row doesn't dump
    several JSON blobs onto the screen by default.
    """

    list_display = (
        "id", "locale", "status", "buffer_metres", "layer_counts",
        "created_at", "started_at", "finished_at",
    )
    list_filter = ("status",)
    search_fields = ("locale__name", "locale__user__username")
    list_select_related = ("locale",)
    readonly_fields = ("id", "created_at", "started_at", "finished_at")

    fieldsets = (
        (None, {
            "fields": ("id", "locale", "status", "buffer_metres", "error"),
        }),
        ("Tidsstämplar", {
            "fields": ("created_at", "started_at", "finished_at"),
        }),
        ("Rådata (stora JSON-svar)", {
            "classes": ("collapse",),
            "fields": ("geometry", *(source.field for source in SOURCES)),
            "description": (
                "Fullständiga Lantmäteriet-svar. Se antal per lager i listan "
                "ovan innan du öppnar det här."
            ),
        }),
    )

    @admin.display(description="Features per lager")
    def layer_counts(self, obj):
        return ", ".join(
            f"{source.label}: {len(getattr(obj, source.field).get('features', []))}"
            for source in SOURCES
        )
