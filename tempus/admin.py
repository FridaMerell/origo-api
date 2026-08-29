from django.contrib import admin
import tempus.models
# Register your models here.


@admin.register(tempus.models.SpeciesCategory)  # Replace 'YourModelName' with the actual model name
class SpeciesCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'label')  # Replace with the actual fields of your model
    search_fields = ('label',)  # Replace with the actual fields you want to search by

@admin.register(tempus.models.Species)  # Replace 'YourModelName' with the actual model name
class SpeciesAdmin(admin.ModelAdmin):
    list_display = ('id', 'swedish_name')  # Replace with the actual fields of your model
    search_fields = ('swedish_name',)  # Replace with the actual fields you want to search by

@admin.register(tempus.models.Phenophase)
class PhenophaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'code')  # Replace with the actual fields of your model
    search_fields = ('code',)  # Replace with the actual fields you want to search by
    list_filter = ('code',)  # Add list filter for the code field

@admin.register(tempus.models.Phenogram)
class PhenogramAdmin(admin.ModelAdmin):
    list_display = ('id', 'species', 'geo_area', 'years', 'peak_week', 'sample_count', 'computed_at')
    search_fields = ('species__swedish_name', 'species__scientific_name', 'geo_area__name')
    list_filter = ('geo_area', 'years', 'declustered')
    readonly_fields = ('computed_at',)

@admin.register(tempus.models.Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'title')  # Replace with the actual fields of your model
    search_fields = ('title',)  # Replace with the actual fields you want to search by
    list_filter = ('title',)  # Add list filter for the name field

@admin.register(tempus.models.GeoArea)
class GeoAreaAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'kind', 'country_code')  # Replace with the actual fields of your model
    search_fields = ('name', 'kind', 'country_code')  # Replace with the actual fields you want to search by
    list_filter = ('kind', 'country_code')  # Add list filter for the kind and country_code fields

@admin.register(tempus.models.Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'name', 'description', 'start_date', 'end_date', 'geo_area', 'route', 'created_at', 'updated_at')
    search_fields = ('name', 'user__username')
    list_filter = ('start_date', 'end_date', 'geo_area', 'route')
    readonly_fields = ('created_at', 'updated_at')