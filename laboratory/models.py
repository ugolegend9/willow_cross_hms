from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from ehr.models import Encounter
from patients.models import Patient


class LabOrder(models.Model):
    class Status(models.TextChoices):
        ORDERED = 'ORDERED', 'Ordered'
        SAMPLE_COLLECTED = 'SAMPLE_COLLECTED', 'Sample collected'
        RESULTED = 'RESULTED', 'Resulted'
        CANCELLED = 'CANCELLED', 'Cancelled'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='lab_orders')
    ordered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='lab_orders_placed')
    # Optional: which encounter this was ordered from, if any -- a standalone
    # order from the patient profile has no encounter, same as how IPD
    # admissions don't require a prior OPD visit.
    encounter = models.ForeignKey(Encounter, on_delete=models.SET_NULL, null=True, blank=True, related_name='lab_orders')
    test_name = models.CharField(max_length=150)
    notes = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ORDERED)
    ordered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ordered_at']

    def __str__(self):
        return f"{self.test_name} — {self.patient.full_name} ({self.get_status_display()})"


class Sample(models.Model):
    lab_order = models.OneToOneField(LabOrder, on_delete=models.CASCADE, related_name='sample')
    barcode = models.CharField(max_length=20, unique=True, editable=False)
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    collected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.barcode

    def save(self, *args, **kwargs):
        if self.barcode:
            return super().save(*args, **kwargs)
        # Same collision-retry pattern as Patient MRN generation: two lab
        # techs collecting at once must not crash either of them.
        for attempt in range(1, 6):
            self.barcode = self._generate_barcode()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                collided = Sample.objects.filter(barcode=self.barcode).exists()
                self.barcode = ''
                if not collided or attempt == 5:
                    raise

    def _generate_barcode(self):
        year = timezone.localdate().year
        last = Sample.objects.filter(barcode__startswith=f"LAB-{year}-").order_by('-barcode').first()
        seq = int(last.barcode.split('-')[-1]) + 1 if last else 1
        return f"LAB-{year}-{seq:06d}"


class LabResult(models.Model):
    lab_order = models.OneToOneField(LabOrder, on_delete=models.CASCADE, related_name='result')
    value = models.CharField(max_length=100)
    unit = models.CharField(max_length=30, blank=True)
    reference_range = models.CharField(max_length=60, blank=True, help_text="e.g. 4.0-11.0")
    is_abnormal = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    entered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        flag = " (abnormal)" if self.is_abnormal else ""
        return f"{self.lab_order.test_name}: {self.value}{self.unit}{flag}"
