from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from patients.models import Patient


class Invoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PARTIAL = 'PARTIAL', 'Partially paid'
        PAID = 'PAID', 'Paid'
        VOID = 'VOID', 'Void'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='invoices')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)

    @property
    def total(self):
        return sum(item.amount for item in self.line_items.all())

    @property
    def amount_paid(self):
        return sum(p.amount for p in self.payments.all())

    @property
    def balance(self):
        return self.total - self.amount_paid

    def __str__(self):
        return f"Invoice #{self.pk} — {self.patient.full_name}"

    def refresh_status(self):
        """Recompute and persist status from actual payments. Call after
        any payment is added or a line item changes."""
        if self.status == self.Status.VOID:
            return
        if self.balance <= 0 and self.total > 0:
            self.status = self.Status.PAID
        elif self.amount_paid > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.UNPAID
        self.save(update_fields=['status'])


class LineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        CARD = 'CARD', 'Card'
        TRANSFER = 'TRANSFER', 'Bank transfer'
        INSURANCE = 'INSURANCE', 'Insurance / HMO'

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    paid_at = models.DateTimeField(auto_now_add=True)
