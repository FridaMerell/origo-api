"""Income received for a house and, optionally, one booking."""

from django.conf import settings
from django.db import models

from .bookings import Booking
from .homes import House


class Income(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="incomes")
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, related_name="incomes", null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    date_received = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="incomes")

    def __str__(self):
        return f"Income of {self.amount} for {self.house}"
