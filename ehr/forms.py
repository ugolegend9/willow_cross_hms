from django import forms
from .models import Encounter, Vitals, Diagnosis, ClinicalNote, Allergy


class EncounterForm(forms.Form):
    """One combined form to record a full clinical encounter: the visit
    reason plus optional vitals, a diagnosis, and a note — saved as
    linked Encounter/Vitals/Diagnosis/ClinicalNote rows in one go."""
    reason = forms.CharField(max_length=255, label="Reason for visit")
    temperature_c = forms.DecimalField(max_digits=4, decimal_places=1, required=False, min_value=25, max_value=45, label="Temp (°C)")
    blood_pressure = forms.CharField(max_length=20, required=False, label="Blood pressure", help_text="e.g. 120/80")
    pulse_bpm = forms.IntegerField(required=False, min_value=20, max_value=300, label="Pulse (bpm)")
    spo2_percent = forms.IntegerField(required=False, min_value=0, max_value=100, label="SpO₂ (%)")
    diagnosis = forms.CharField(max_length=255, required=False, label="Diagnosis")
    note = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False, label="Clinical note")

    def save(self, patient, clinician):
        data = self.cleaned_data
        encounter = Encounter.objects.create(patient=patient, clinician=clinician, reason=data['reason'])
        if any(data.get(f) not in (None, '') for f in ('temperature_c', 'blood_pressure', 'pulse_bpm', 'spo2_percent')):
            Vitals.objects.create(
                encounter=encounter,
                temperature_c=data.get('temperature_c'),
                blood_pressure=data.get('blood_pressure') or '',
                pulse_bpm=data.get('pulse_bpm'),
                spo2_percent=data.get('spo2_percent'),
            )
        if data.get('diagnosis'):
            Diagnosis.objects.create(encounter=encounter, description=data['diagnosis'])
        if data.get('note'):
            ClinicalNote.objects.create(encounter=encounter, author=clinician, body=data['note'])
        return encounter


class AllergyForm(forms.ModelForm):
    class Meta:
        model = Allergy
        fields = ['substance', 'reaction', 'severity']
