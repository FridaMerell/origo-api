from django.conf import settings
from django.db import models


class House(models.Model):
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="houses")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


#  Vistelser
class Booking(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="bookings")
    visitor = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking by {self.visitor} for {self.house} from {self.start_date} to {self.end_date}"


class BookingRequest(models.Model):
    house = models.ForeignKey(
        House, on_delete=models.CASCADE, related_name="booking_requests"
    )
    requester = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking request by {self.requester} for {self.house} from {self.start_date} to {self.end_date} - Status: {self.status}"


class CheckOut(models.Model):
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="check_outs"
    )
    check_out_time = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    files = models.JSONField(
        blank=True, default=list
    )  # Store file metadata as a list of dictionaries

    def __str__(self):
        return f"Check-out for {self.booking} at {self.check_out_time}"


# Projektering


class Venture(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.IntegerField(default=0)
    budget = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(
        blank=True, default=list
    )  # Store file metadata as a list of dictionaries
    house = models.ForeignKey(
        House, on_delete=models.CASCADE, related_name="ventures", null=True, blank=True
    )

    def __str__(self):
        return self.name

class VersoUpdate(models.Model):
    venture = models.ForeignKey(
        Venture, on_delete=models.CASCADE, related_name="updates", null=True, blank=True
    )
    task = models.ForeignKey(
        "VentureTask", on_delete=models.CASCADE, related_name="updates", null=True, blank=True
    )
    house = models.ForeignKey(
        House, on_delete=models.CASCADE, related_name="updates", null=True, blank=True
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="verso_updates",
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    files = models.JSONField(
        blank=True, default=list
    )  # Store file metadata as a list of dictionaries
    def __str__(self):
        return f"Update: {self.title} for Venture: {self.venture.name if self.venture else 'N/A'} and Task: {self.task.name if self.task else 'N/A'}"


class VentureTask(models.Model):
    venture = models.ForeignKey(Venture, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task: {self.name} for Venture: {self.venture.name}"


# Ekonomisk oversikt


class Expense(models.Model):
    venture = models.ForeignKey(
        Venture,
        on_delete=models.CASCADE,
        related_name="expenses",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    date_incurred = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    house = models.ForeignKey(
        House, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True
    )

    def __str__(self):
        return f'Expense of {self.amount} for Venture: {self.venture.name if self.venture else "N/A"}'

