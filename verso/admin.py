from django.contrib import admin
from verso.models import House, Booking, BookingRequest, CheckOut, Venture, VentureTask, Expense
# Register your models here.
@admin.register(House)
class HouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'created_at', 'updated_at')

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('house', 'visitor', 'start_date', 'end_date', 'created_at', 'updated_at')

@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = ('house', 'requester', 'start_date', 'end_date', 'status', 'created_at', 'updated_at')

@admin.register(Venture)
class VentureAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'priority', 'budget', 'created_at', 'updated_at')

@admin.register(VentureTask)
class VentureTaskAdmin(admin.ModelAdmin):
    list_display = ('venture', 'name', 'description', 'completed', 'created_at', 'updated_at')

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('venture', 'amount', 'description', 'date_incurred', 'created_at', 'updated_at', 'house')