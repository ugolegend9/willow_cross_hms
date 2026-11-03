from django import forms
from ehr.models import Encounter
from .models import OPDVisit, Prescription, Referral


class OPDVisitForm(forms.Form):
    """A full OPD consultation in one submit: the chief complaint (which
    also opens a linked EHR encounter), an optional prescription, and an
    optional referral to another department."""
    chief_complaint = forms.CharField(max_length=255, label="Chief complaint")
    drug_name = forms.CharField(max_length=150, required=False, label="Prescribe — drug name")
    dosage = forms.CharField(max_length=100, required=False, label="Dosage")
    frequency = forms.CharField(max_length=100, required=False, label="Frequency")
    duration_days = forms.IntegerField(required=False, min_value=1, label="Duration (days)")
    referral_department = forms.CharField(max_length=100, required=False, label="Refer to department")
    referral_reason = forms.CharField(max_length=255, required=False, label="Referral reason")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('drug_name') and not (cleaned.get('dosage') and cleaned.get('frequency') and cleaned.get('duration_days')):
            raise forms.ValidationError("Dosage, frequency, and duration are all required when prescribing a drug.")
        if cleaned.get('referral_department') and not cleaned.get('referral_reason'):
            raise forms.ValidationError("A referral needs a reason.")
        return cleaned

    def save(self, patient, doctor, appointment=None):
        data = self.cleaned_data
        if appointment is not None:
            # Lock the appointment and re-check: another doctor may have
            # consulted it in the moment since the view's own check, or since
            # the page loaded. Without this, two near-simultaneous
            # consultations of the same appointment would both pass and
            # create two OPDVisits -- the same lesson as pharmacy dispensing
            # and lab result entry.
            appointment = type(appointment).objects.select_for_update().get(pk=appointment.pk)
            if appointment.status != appointment.Status.CHECKED_IN:
                raise forms.ValidationError("That appointment was just consulted by someone else.")

        encounter = Encounter.objects.create(patient=patient, clinician=doctor, reason=data['chief_complaint'])
        visit = OPDVisit.objects.create(
            patient=patient, doctor=doctor, encounter=encounter, chief_complaint=data['chief_complaint'],
        )
        if data.get('drug_name'):
            Prescription.objects.create(
                opd_visit=visit, drug_name=data['drug_name'], dosage=data['dosage'],
                frequency=data['frequency'], duration_days=data['duration_days'],
            )
        if data.get('referral_department'):
            Referral.objects.create(opd_visit=visit, to_department=data['referral_department'], reason=data['referral_reason'])
        if appointment is not None:
            appointment.status = appointment.Status.COMPLETED
            appointment.save(update_fields=['status'])
        return visit
