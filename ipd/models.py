from django.conf import settings
from django.db import models
from patients.models import Patient


class Ward(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Bed(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        OCCUPIED = 'OCCUPIED', 'Occupied'
        MAINTENANCE = 'MAINTENANCE', 'Under maintenance'

    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        unique_together = ('ward', 'bed_number')

    def __str__(self):
        return f"{self.ward.name} — Bed {self.bed_number}"


class Admission(models.Model):
    class Status(models.TextChoices):
        ADMITTED = 'ADMITTED', 'Admitted'
        DISCHARGED = 'DISCHARGED', 'Discharged'
        TRANSFERRED = 'TRANSFERRED', 'Transferred'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='admissions')
    bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, related_name='admissions')
    attending_doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    admitted_at = models.DateTimeField(auto_now_add=True)
    discharged_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ADMITTED)
    diagnosis_summary = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.patient.full_name} — {self.get_status_display()}"


class CarePlan(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='care_plans')
    instructions = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MedicationAdministration(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='mar_entries')
    drug_name = models.CharField(max_length=150)
    dose = models.CharField(max_length=100)
    administered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    administered_at = models.DateTimeField(auto_now_add=True)
