from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Invoice, LineItem, Payment


@receiver([post_save, post_delete], sender=Payment)
@receiver([post_save, post_delete], sender=LineItem)
def keep_invoice_status_in_sync(sender, instance, **kwargs):
    """Invoice.status is stored, so it must be recomputed whenever a payment or
    charge is added, changed or removed, including from the Django admin,
    scripts and the seed command, not only from our own view."""
    try:
        invoice = Invoice.objects.get(pk=instance.invoice_id)
    except Invoice.DoesNotExist:  # the whole invoice is being deleted
        return
    invoice.refresh_status()
