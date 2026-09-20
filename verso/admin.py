from django.contrib import admin
from verso.models import House, Booking, BookingRequest, CheckOut, Venture, VentureTask, Expense, VersoUpdate, Drawing, DrawingPage, Photo, Album, Tag, Person, PersonRelation, HistoryEvent, Document
from origo.admin import site

@admin.register(Document, site=site)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'house', 'venture', 'content_type', 'document_date', 'author', 'created_at')
    list_filter = ('house', 'content_type')
    filter_horizontal = ('tags', 'people')

@admin.register(Person, site=site)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'house', 'birth_date', 'death_date', 'relation')
    list_filter = ('house',)

@admin.register(PersonRelation, site=site)
class PersonRelationAdmin(admin.ModelAdmin):
    list_display = ('person', 'kind', 'label', 'related', 'house', 'start_year', 'end_year')
    list_filter = ('house', 'kind')

@admin.register(HistoryEvent, site=site)
class HistoryEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'house', 'date_start', 'date_precision', 'place')
    list_filter = ('house', 'date_precision')
    filter_horizontal = ('people', 'photos')


@admin.register(Photo, site=site)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ('title', 'house', 'venture', 'stage', 'taken_at', 'author', 'created_at')
    list_filter = ('house', 'stage')
    filter_horizontal = ('albums', 'tags')

@admin.register(Album, site=site)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ('name', 'house', 'venture', 'kind', 'created_at')
    list_filter = ('house', 'kind')

@admin.register(Tag, site=site)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'house')
    list_filter = ('house',)

@admin.register(Drawing, site=site)
class DrawingAdmin(admin.ModelAdmin):
    list_display = ('name', 'house', 'venture', 'unit', 'author', 'created_at', 'updated_at')
    list_filter = ('house', 'unit')

@admin.register(DrawingPage, site=site)
class DrawingPageAdmin(admin.ModelAdmin):
    list_display = ('drawing', 'name', 'order', 'width', 'height', 'updated_at')
    list_filter = ('drawing',)

@admin.register(VersoUpdate, site=site)
class VersoUpdateAdmin(admin.ModelAdmin):
    list_display = ('venture', 'task', 'author', 'title', 'created_at', 'updated_at')

@admin.register(House, site=site)
class HouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'created_at', 'updated_at')

@admin.register(Booking, site=site)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('house', 'visitor', 'start_date', 'end_date', 'created_at', 'updated_at')

@admin.register(BookingRequest, site=site)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = ('house', 'requester', 'start_date', 'end_date', 'status', 'created_at', 'updated_at')

@admin.register(Venture, site=site)
class VentureAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'priority', 'budget', 'created_at', 'updated_at')

@admin.register(VentureTask, site=site)
class VentureTaskAdmin(admin.ModelAdmin):
    list_display = ('venture', 'name', 'description', 'completed', 'created_at', 'updated_at')

@admin.register(Expense, site=site)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('venture', 'amount', 'description', 'date_incurred', 'created_at', 'updated_at', 'house')
