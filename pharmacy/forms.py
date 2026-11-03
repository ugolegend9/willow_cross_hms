from django import forms
from django.db import transaction
from django.utils import timezone

from .models import Batch, Drug, DispenseRecord


class DrugForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = ['name', 'strength', 'unit_price', 'reorder_level', 'is_controlled']
        widgets = {'strength': forms.TextInput(attrs={'placeholder': 'e.g. 250mg'})}


class ReceiveStockForm(forms.ModelForm):
    drug = forms.ModelChoiceField(queryset=Drug.objects.order_by('name'))

    class Meta:
        model = Batch
        fields = ['drug', 'batch_number', 'quantity', 'expiry_date']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}

    def clean_expiry_date(self):
        expiry = self.cleaned_data['expiry_date']
        if expiry < timezone.localdate():
            raise forms.ValidationError("Expiry date is in the past. Check the batch details.")
        return expiry


class DispenseForm(forms.Form):
    """Dispensing one drug to one patient. Stock comes out oldest-expiry-first
    (FEFO) across that drug's batches, chosen automatically -- the pharmacist
    picks the drug and quantity, not the batch."""
    drug = forms.ModelChoiceField(queryset=Drug.objects.order_by('name'))
    quantity = forms.IntegerField(min_value=1)
    acknowledge_allergy = forms.BooleanField(
        required=False, label="I've reviewed this allergy and it's safe to proceed",
    )

    def __init__(self, *args, patient=None, **kwargs):
        self.patient = patient
        super().__init__(*args, **kwargs)

    def _allergy_conflict(self, drug):
        """Best-effort name match: allergies are recorded as free text
        (e.g. "Penicillin"), not linked to the drug catalog."""
        name = drug.name.lower()
        for allergy in self.patient.allergies.all():
            substance = allergy.substance.lower()
            if substance in name or name in substance:
                return allergy
        return None

    def clean(self):
        cleaned = super().clean()
        drug, quantity = cleaned.get('drug'), cleaned.get('quantity')
        if not (drug and quantity):
            return cleaned

        available = drug.total_stock
        if quantity > available:
            self.add_error('quantity', f"Only {available} unit{'s' if available != 1 else ''} of {drug} in stock.")

        if self.patient is not None:
            conflict = self._allergy_conflict(drug)
            if conflict and not cleaned.get('acknowledge_allergy'):
                raise forms.ValidationError(
                    f"{self.patient.full_name} has a recorded allergy to {conflict.substance}. "
                    "Tick the acknowledgement box to proceed, or choose a different drug."
                )
        return cleaned

    def save(self, patient, dispensed_by, prescription=None):
        drug, quantity = self.cleaned_data['drug'], self.cleaned_data['quantity']
        today = timezone.localdate()
        with transaction.atomic():
            if prescription is not None:
                # Lock the prescription row and re-check: another pharmacist
                # may have dispensed it in the moment since this page loaded,
                # or since the view's own check just before this call. Without
                # this, two near-simultaneous dispenses would both pass that
                # check and the second INSERT would hit the OneToOneField's
                # unique constraint as a raw, unhandled IntegrityError.
                prescription = type(prescription).objects.select_for_update().get(pk=prescription.pk)
                if hasattr(prescription, 'dispense_record'):
                    raise forms.ValidationError("This prescription was just dispensed by someone else.")
            # Re-check stock under a lock too: it may have moved since clean() ran.
            batches = (drug.batches.select_for_update()
                       .filter(quantity__gt=0, expiry_date__gte=today)
                       .order_by('expiry_date'))
            remaining = quantity
            for batch in batches:
                if remaining <= 0:
                    break
                take = min(batch.quantity, remaining)
                batch.quantity -= take
                batch.save(update_fields=['quantity'])
                remaining -= take
            if remaining > 0:
                raise forms.ValidationError(f"Only {quantity - remaining} unit(s) of {drug} were actually available. Nothing was dispensed.")
            return DispenseRecord.objects.create(
                drug=drug, patient=patient, quantity=quantity, dispensed_by=dispensed_by, prescription=prescription,
            )
