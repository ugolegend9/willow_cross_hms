from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from patients.models import Patient


class Drug(models.Model):
    name = models.CharField(max_length=150)
    strength = models.CharField(max_length=50, blank=True, help_text="e.g. 250mg")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    reorder_level = models.PositiveIntegerField(default=20)
    is_controlled = models.BooleanField(default=False, help_text="Narcotic / controlled substance")

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['name', 'strength'], name='unique_drug_name_strength')]

    def __str__(self):
        return f"{self.name} {self.strength}".strip()

    @property
    def total_stock(self):
        """Unexpired stock only -- an expired batch is not usable, however the
        raw database row still says a positive quantity."""
        today = timezone.localdate()
        return sum(b.quantity for b in self.batches.all() if b.expiry_date >= today)

    @property
    def is_low_stock(self):
        return self.total_stock <= self.reorder_level

    @property
    def has_expiring_batch(self):
        """Any unexpired batch due within 30 days -- worth a pharmacist's attention."""
        soon = timezone.localdate() + timezone.timedelta(days=30)
        today = timezone.localdate()
        return any(today <= b.expiry_date <= soon for b in self.batches.all())


class Batch(models.Model):
    class Meta:
        verbose_name_plural = 'batches'
        ordering = ['expiry_date']
        constraints = [models.UniqueConstraint(fields=['drug', 'batch_number'], name='unique_batch_number_per_drug')]

    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    expiry_date = models.DateField()

    def __str__(self):
        return f"{self.drug} — batch {self.batch_number} (exp {self.expiry_date})"

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()


class DispenseRecord(models.Model):
    # PROTECT, not CASCADE: a dispense record is audit history (like an
    # invoice or a lab result) and must survive even if the catalog entry
    # for the drug is later removed.
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name='dispense_records')
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, related_name='dispense_records')
    # Optional: which prescription this fulfilled, if any. A pharmacist can
    # also dispense something a patient asks for directly, with no OPD visit.
    prescription = models.OneToOneField(
        'opd.Prescription', on_delete=models.SET_NULL, null=True, blank=True, related_name='dispense_record',
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-dispensed_at']

    def __str__(self):
        return f"{self.quantity} × {self.drug} for {self.patient}"
