from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from accounts.decorators import role_required
from accounts.permissions import EHR_ROLES
from patients.models import Patient
from .forms import EncounterForm, AllergyForm


@login_required
@role_required(*EHR_ROLES)
def patient_ehr(request, pk):
    patient = get_object_or_404(Patient, pk=pk)

    encounter_form = EncounterForm()
    allergy_form = AllergyForm()

    if request.method == 'POST':
        if 'add_encounter' in request.POST:
            encounter_form = EncounterForm(request.POST)
            if encounter_form.is_valid():
                encounter_form.save(patient, request.user)
                return redirect('ehr:patient_ehr', pk=pk)
        elif 'add_allergy' in request.POST:
            allergy_form = AllergyForm(request.POST)
            if allergy_form.is_valid():
                allergy = allergy_form.save(commit=False)
                allergy.patient = patient
                allergy.save()
                return redirect('ehr:patient_ehr', pk=pk)

    encounters = (patient.encounters
                  .select_related('clinician', 'opd_visit')
                  .prefetch_related('vitals', 'diagnoses', 'notes', 'opd_visit__prescriptions__dispense_record', 'opd_visit__referrals')
                  .order_by('-date'))

    lab_orders = patient.lab_orders.select_related('ordered_by', 'result').order_by('-ordered_at')

    return render(request, 'ehr/patient_ehr.html', {
        'patient': patient,
        'encounters': encounters,
        'allergies': patient.allergies.all(),
        'lab_orders': lab_orders,
        'encounter_form': encounter_form,
        'allergy_form': allergy_form,
        'active_nav': 'patients',
    })
