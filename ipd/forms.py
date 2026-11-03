import re

from django import forms
from django.db import transaction

from accounts.models import User, Role
from .models import Admission, Bed, CarePlan, MedicationAdministration, Ward


class AdmissionForm(forms.ModelForm):
    bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(status=Bed.Status.AVAILABLE).select_related('ward').order_by('ward__name', 'bed_number'),
        label="Bed",
    )
    attending_doctor = forms.ModelChoiceField(queryset=User.objects.filter(role=Role.DOCTOR).order_by('first_name'))

    class Meta:
        model = Admission
        fields = ['bed', 'attending_doctor', 'diagnosis_summary']
        widgets = {'diagnosis_summary': forms.TextInput(attrs={'placeholder': 'e.g. Severe malaria, for observation'})}

    def save(self, patient, commit=True):
        admission = super().save(commit=False)
        admission.patient = patient
        if commit:
            # The bed list was "available" when the form rendered, but two
            # staff can submit for the same bed at once. Lock the row and
            # re-check inside a transaction so only one of them wins.
            with transaction.atomic():
                bed = Bed.objects.select_for_update().get(pk=admission.bed_id)
                if bed.status != Bed.Status.AVAILABLE:
                    raise forms.ValidationError(f"{bed} was just taken. Please choose another bed.")
                admission.save()
                bed.status = Bed.Status.OCCUPIED
                bed.save(update_fields=['status'])
        return admission


class CarePlanForm(forms.ModelForm):
    class Meta:
        model = CarePlan
        fields = ['instructions']
        widgets = {'instructions': forms.Textarea(attrs={'rows': 3, 'placeholder': 'e.g. IV fluids 8-hourly, monitor temperature'})}


class MedicationAdministrationForm(forms.ModelForm):
    class Meta:
        model = MedicationAdministration
        fields = ['drug_name', 'dose']


class WardForm(forms.ModelForm):
    class Meta:
        model = Ward
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'e.g. Paediatrics'})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Ward.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"A ward called “{name}” already exists.")
        return name


class AddBedsForm(forms.Form):
    """Add one or many beds to a ward in a single go. It is all-or-nothing:
    if any number already exists in that ward, nothing is created."""
    MAX_AT_ONCE = 50

    ward = forms.ModelChoiceField(queryset=Ward.objects.order_by('name'))
    bed_numbers = forms.CharField(
        label="Bed numbers",
        help_text="One or more, separated by commas, spaces or new lines. No spaces inside a number.",
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'G-04, G-05, G-06'}),
    )

    def clean_bed_numbers(self):
        # dict.fromkeys drops repeats but keeps the order they were typed in
        numbers = list(dict.fromkeys(n for n in re.split(r'[,\s]+', self.cleaned_data['bed_numbers']) if n))
        if not numbers:
            raise forms.ValidationError("Enter at least one bed number.")
        if len(numbers) > self.MAX_AT_ONCE:
            raise forms.ValidationError(f"Add at most {self.MAX_AT_ONCE} beds at a time.")
        limit = Bed._meta.get_field('bed_number').max_length
        too_long = [n for n in numbers if len(n) > limit]
        if too_long:
            raise forms.ValidationError(f"Bed numbers can be at most {limit} characters: {', '.join(too_long)}")
        return numbers

    def clean(self):
        cleaned = super().clean()
        ward, numbers = cleaned.get('ward'), cleaned.get('bed_numbers')
        if ward and numbers:
            existing = sorted(Bed.objects.filter(ward=ward, bed_number__in=numbers).values_list('bed_number', flat=True))
            if existing:
                raise forms.ValidationError(f"Already in {ward.name}: {', '.join(existing)}. Nothing was added.")
        return cleaned

    def save(self):
        ward = self.cleaned_data['ward']
        with transaction.atomic():
            return Bed.objects.bulk_create([Bed(ward=ward, bed_number=n) for n in self.cleaned_data['bed_numbers']])
