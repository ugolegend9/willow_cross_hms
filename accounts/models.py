from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = 'ADMIN', 'Administrator'
    DOCTOR = 'DOCTOR', 'Doctor'
    NURSE = 'NURSE', 'Nurse'
    PHARMACIST = 'PHARMACIST', 'Pharmacist'
    LAB_TECH = 'LAB_TECH', 'Lab Technician'
    BILLING = 'BILLING', 'Billing Officer'
    FRONT_DESK = 'FRONT_DESK', 'Front Desk'


class User(AbstractUser):
    """Staff account. Patients are a separate model (patients.Patient) and
    do not log in through this system in Phase 1."""
    staff_id = models.CharField(max_length=20, unique=True, help_text="e.g. WCH-2291")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FRONT_DESK)
    department = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
