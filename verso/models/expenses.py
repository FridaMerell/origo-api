"""Costs attributed to a house and, optionally, one venture."""

from django.conf import settings
from django.db import models

from .homes import House
from .ventures import Venture


class Expense(models.Model):
    venture = models.ForeignKey(Venture, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    date_incurred = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")

    def __str__(self):
        venture_name = self.venture.name if self.venture else "N/A"
        return f"Expense of {self.amount} for Venture: {venture_name}"
