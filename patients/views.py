from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from accounts.permissions import REGISTER_PATIENT_ROLES
from .forms import PatientForm
from .models import Patient


@login_required
def patient_list(request):
    query = request.GET.get('q', '').strip()
    patients = Patient.objects.all()
    # Every word must match something (MRN, first or last name), so a full
    # name like "Chidinma Eze" works in either order.
    for token in query.split():
        patients = patients.filter(
            Q(mrn__icontains=token) | Q(first_name__icontains=token) | Q(last_name__icontains=token)
        )
    return render(request, 'patients/patient_list.html', {
        'patients': patients[:100], 'query': query, 'active_nav': 'patients',
    })


@login_required
@role_required(*REGISTER_PATIENT_ROLES)
def patient_register(request):
    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            patient = form.save()
            return redirect('patients:detail', pk=patient.pk)
    else:
        form = PatientForm()
    return render(request, 'patients/patient_form.html', {'form': form, 'active_nav': 'patients'})


@login_required
def patient_detail(request, pk):
    # Viewing a patient stays open to any logged-in staff: doctors, nurses,
    # pharmacists and lab staff all need to look someone up. Only creating a
    # new record is restricted, per the spec (Front Desk / Admin).
    patient = get_object_or_404(Patient, pk=pk)
    return render(request, 'patients/patient_detail.html', {'patient': patient, 'active_nav': 'patients'})
