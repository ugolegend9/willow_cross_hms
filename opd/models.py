from django.conf import settings
from django.db import models
from patients.models import Patient
from ehr.models import Encounter


class OPDVisit(models.Model):
    class Meta:
        verbose_name = 'OPD visit'
        verbose_name_plural = 'OPD visits'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='opd_visits')
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    encounter = models.OneToOneField(Encounter, on_delete=models.CASCADE, related_name='opd_visit', null=True, blank=True)
    chief_complaint = models.CharField(max_length=255)
    visited_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OPD: {self.patient.full_name} — {self.visited_at:%Y-%m-%d}"


class Prescription(models.Model):
    opd_visit = models.ForeignKey(OPDVisit, on_delete=models.CASCADE, related_name='prescriptions')
    drug_name = models.CharField(max_length=150)
    dosage = models.CharField(max_length=100)
    frequency = models.CharField(max_length=100)
    duration_days = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.drug_name} for {self.opd_visit.patient.full_name}"


class Referral(models.Model):
    opd_visit = models.ForeignKey(OPDVisit, on_delete=models.CASCADE, related_name='referrals')
    to_department = models.CharField(max_length=100)
    reason = models.CharField(max_length=255)
