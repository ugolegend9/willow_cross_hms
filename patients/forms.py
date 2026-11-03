from django import forms
from .models import Patient, NextOfKin


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ['first_name', 'last_name', 'date_of_birth', 'gender', 'blood_group',
                  'phone_number', 'email', 'address']
        widgets = {'date_of_birth': forms.DateInput(attrs={'type': 'date'})}


class NextOfKinForm(forms.ModelForm):
    class Meta:
        model = NextOfKin
        fields = ['full_name', 'relationship', 'phone_number']
