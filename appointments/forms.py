from django import forms
from accounts.models import User, Role
from patients.models import Patient
from .models import Appointment


class AppointmentForm(forms.ModelForm):
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.order_by('-registered_at'),
        widget=forms.Select(attrs={'class': 'searchable'}),
    )
    doctor = forms.ModelChoiceField(queryset=User.objects.filter(role=Role.DOCTOR).order_by('first_name'))

    class Meta:
        model = Appointment
        fields = ['patient', 'doctor', 'scheduled_for', 'department', 'notes']
        widgets = {
            'scheduled_for': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
