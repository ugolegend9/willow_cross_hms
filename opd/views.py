from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.decorators import role_required
from accounts.permissions import CONSULT_ROLES
from appointments.models import Appointment
from patients.models import Patient
from .forms import OPDVisitForm


@login_required
def opd_queue(request):
    """Today's checked-in patients, waiting to be seen."""
    waiting = (Appointment.objects
               .filter(status=Appointment.Status.CHECKED_IN, scheduled_for__date=timezone.localdate())
               .select_related('patient', 'doctor')
               .order_by('scheduled_for'))
    return render(request, 'opd/queue.html', {'waiting': waiting, 'active_nav': 'opd'})


@login_required
@role_required(*CONSULT_ROLES)
def opd_consult(request, patient_pk, appointment_pk=None):
    patient = get_object_or_404(Patient, pk=patient_pk)
    # The appointment must belong to this patient. Without this check, a
    # mismatched URL would record the visit against one patient and quietly
    # mark another patient's appointment as completed.
    appointment = get_object_or_404(Appointment, pk=appointment_pk, patient=patient) if appointment_pk else None
    # Only a checked-in appointment can be consulted. Without this, a stale
    # tab, a double click, or the back button could create a second
    # OPDVisit/Encounter/Prescription for an appointment already consulted,
    # or consult one that was cancelled -- the same bug class already fixed
    # once for pharmacy dispensing and once for lab result entry.
    if appointment is not None and appointment.status != Appointment.Status.CHECKED_IN:
        messages.info(request, f"That appointment is {appointment.get_status_display().lower()} and can't be consulted.")
        return redirect('patients:detail', pk=patient.pk)

    if request.method == 'POST':
        form = OPDVisitForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save(patient, request.user, appointment)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"OPD visit recorded for {patient.full_name}.")
                return redirect('ehr:patient_ehr', pk=patient.pk)
    else:
        form = OPDVisitForm()

    return render(request, 'opd/visit_form.html', {
        'form': form, 'patient': patient, 'appointment': appointment, 'active_nav': 'opd',
    })
