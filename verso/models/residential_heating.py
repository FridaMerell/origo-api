"""Connection from a house to an external ResidentialHeatingScheduler API."""

from django.db import models

from .homes import House


class ResidentialHeating(models.Model):
    house = models.OneToOneField(House, on_delete=models.CASCADE, related_name="residential_heating")
    base_url = models.URLField()
    token = models.CharField(max_length=255)
    device = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ResidentialHeating for {self.house}"
