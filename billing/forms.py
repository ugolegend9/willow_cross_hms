from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from patients.models import Patient
from .models import Invoice, LineItem, Payment


class InvoicePatientForm(forms.Form):
    patient = forms.ModelChoiceField(queryset=Patient.objects.order_by('-registered_at'))


class LineItemForm(forms.ModelForm):
    class Meta:
        model = LineItem
        fields = ['description', 'amount']
        widgets = {'amount': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'})}

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


class BaseLineItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        # Blank extra rows have empty cleaned_data; they don't count.
        filled = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not filled:
            raise forms.ValidationError("Add at least one line item.")


LineItemFormSet = inlineformset_factory(
    Invoice, LineItem, form=LineItemForm, formset=BaseLineItemFormSet,
    fields=['description', 'amount'], extra=3, can_delete=True,
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['amount', 'method']

    def __init__(self, *args, invoice=None, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError("Payment amount must be greater than zero.")
        if self.invoice is not None and amount > self.invoice.balance:
            raise forms.ValidationError(
                f"That's more than the outstanding balance of ₦{self.invoice.balance:,.2f}."
            )
        return amount
