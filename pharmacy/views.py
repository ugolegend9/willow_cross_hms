from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from accounts.permissions import PHARMACY_ROLES
from opd.models import Prescription
from patients.models import Patient
from .forms import DispenseForm, DrugForm, ReceiveStockForm
from .models import Drug


@login_required
@role_required(*PHARMACY_ROLES)
def pharmacy_queue(request):
    pending = (Prescription.objects
               .filter(dispense_record__isnull=True)
               .select_related('opd_visit__patient', 'opd_visit__doctor')
               .order_by('opd_visit__visited_at'))
    return render(request, 'pharmacy/queue.html', {'pending': pending, 'active_nav': 'pharmacy'})


def _guess_drug(prescription):
    """Best-effort match from the prescription's free-text drug name to the
    catalog, so the pharmacist doesn't have to retype what the doctor wrote."""
    if not prescription:
        return None
    words = prescription.drug_name.split()
    if not words:  # the app's own forms never allow this, but the admin could
        return None
    return Drug.objects.filter(name__icontains=words[0]).first()


@login_required
@role_required(*PHARMACY_ROLES)
def dispense(request, patient_pk, prescription_pk=None):
    patient = get_object_or_404(Patient, pk=patient_pk)
    # A prescription in the URL must belong to this patient -- otherwise a
    # mismatched link could dispense the right drug against the wrong chart.
    prescription = get_object_or_404(Prescription, pk=prescription_pk, opd_visit__patient=patient) if prescription_pk else None
    if prescription and hasattr(prescription, 'dispense_record'):
        messages.info(request, "That prescription has already been dispensed.")
        return redirect('pharmacy:queue')

    if request.method == 'POST':
        form = DispenseForm(request.POST, patient=patient)
        if form.is_valid():
            try:
                record = form.save(patient, request.user, prescription)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"Dispensed {record.quantity} × {record.drug} to {patient.full_name}.")
                return redirect('patients:detail', pk=patient.pk)
    else:
        initial = {'drug': _guess_drug(prescription).pk} if _guess_drug(prescription) else {}
        form = DispenseForm(patient=patient, initial=initial)

    return render(request, 'pharmacy/dispense_form.html', {
        'form': form, 'patient': patient, 'prescription': prescription, 'active_nav': 'pharmacy',
    })


@login_required
@role_required(*PHARMACY_ROLES)
def inventory(request):
    drug_form, stock_form = DrugForm(), ReceiveStockForm()

    if request.method == 'POST':
        if 'add_drug' in request.POST:
            drug_form = DrugForm(request.POST)
            if drug_form.is_valid():
                drug = drug_form.save()
                messages.success(request, f"{drug} added to the catalog. Receive stock for it below.")
                return redirect('pharmacy:inventory')
        elif 'add_batch' in request.POST:
            stock_form = ReceiveStockForm(request.POST)
            if stock_form.is_valid():
                batch = stock_form.save()
                messages.success(request, f"Received {batch.quantity} units of {batch.drug} (batch {batch.batch_number}).")
                return redirect('pharmacy:inventory')

    drugs = Drug.objects.prefetch_related('batches')
    return render(request, 'pharmacy/inventory.html', {
        'drugs': drugs, 'drug_form': drug_form, 'stock_form': stock_form, 'active_nav': 'pharmacy',
    })
