import re
from django import forms
from .models import LabOrder, LabResult


class OrderLabTestForm(forms.ModelForm):
    class Meta:
        model = LabOrder
        fields = ['test_name', 'notes']
        widgets = {'test_name': forms.TextInput(attrs={'placeholder': 'e.g. Full Blood Count'})}


class EnterResultForm(forms.ModelForm):
    class Meta:
        model = LabResult
        fields = ['value', 'unit', 'reference_range', 'is_abnormal', 'notes']
        widgets = {'reference_range': forms.TextInput(attrs={'placeholder': 'e.g. 4.0-11.0'})}
        labels = {'is_abnormal': "Flag as abnormal"}

    def clean(self):
        cleaned = super().clean()
        value, ref_range = cleaned.get('value'), cleaned.get('reference_range')
        auto = self._auto_detect_abnormal(value, ref_range)
        # When the value and range are both plain numbers, the comparison is
        # authoritative -- it overrides whatever the checkbox says, the same
        # way vitals validation doesn't defer to a free-text opinion.
        if auto is not None:
            cleaned['is_abnormal'] = auto
        return cleaned

    @staticmethod
    def _auto_detect_abnormal(value, ref_range):
        if not value or not ref_range:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$', ref_range or '')
        if not match:
            return None
        low, high = float(match.group(1)), float(match.group(2))
        return not (low <= number <= high)
