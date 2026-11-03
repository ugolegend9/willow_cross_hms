from django.conf import settings
from django.db import models
from patients.models import Patient


class Encounter(models.Model):
    """A single clinical touchpoint — one OPD visit, one admission day, etc."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='encounters')
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255)

    def __str__(self):
        return f"Encounter: {self.patient.full_name} — {self.date:%Y-%m-%d}"


class Vitals(models.Model):
    class Meta:
        verbose_name_plural = 'vitals'

    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name='vitals')
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    blood_pressure = models.CharField(max_length=20, blank=True, help_text="e.g. 120/80")
    pulse_bpm = models.PositiveIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True)
    spo2_percent = models.PositiveIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)


class Allergy(models.Model):
    class Meta:
        verbose_name_plural = 'allergies'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='allergies')
    substance = models.CharField(max_length=150)
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=20, choices=[('MILD', 'Mild'), ('MODERATE', 'Moderate'), ('SEVERE', 'Severe')])

    def __str__(self):
        return f"{self.patient.full_name}: {self.substance} ({self.severity})"


class Diagnosis(models.Model):
    class Meta:
        verbose_name_plural = 'diagnoses'

    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name='diagnoses')
    description = models.CharField(max_length=255)
    icd_code = models.CharField('ICD-10 code', max_length=10, blank=True)


class ClinicalNote(models.Model):
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
