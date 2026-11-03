from django.conf import settings
from django.db import models
from patients.models import Patient


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        CHECKED_IN = 'CHECKED_IN', 'Checked in'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        NO_SHOW = 'NO_SHOW', 'No show'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='appointments')
    scheduled_for = models.DateTimeField()
    department = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['scheduled_for']

    def __str__(self):
        return f"{self.patient.full_name} with {self.doctor} — {self.scheduled_for:%d %b %Y %H:%M}"
