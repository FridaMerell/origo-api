"""Visits, booking requests, and check-outs for a house."""

from django.db import models

from .homes import House


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
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="booking_requests")
    requester = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking request by {self.requester} for {self.house} from {self.start_date} to {self.end_date} - Status: {self.status}"


class CheckOut(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="check_outs")
    check_out_time = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    files = models.JSONField(blank=True, default=list)

    def __str__(self):
        return f"Check-out for {self.booking} at {self.check_out_time}"
