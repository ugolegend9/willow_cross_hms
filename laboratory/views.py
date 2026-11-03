from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.permissions import LAB_ORDER_ROLES, LAB_ROLES
from patients.models import Patient
from .forms import EnterResultForm, OrderLabTestForm
from .models import LabOrder, Sample

_S = LabOrder.Status
# Enforced server-side, the same lesson as appointments: hiding a button in
# the template is not a control, since anyone can POST to the URL directly.
ALLOWED_TRANSITIONS = {
    _S.ORDERED.value: {_S.SAMPLE_COLLECTED.value, _S.CANCELLED.value},
    _S.SAMPLE_COLLECTED.value: {_S.RESULTED.value, _S.CANCELLED.value},
}


@login_required
@role_required(*LAB_ROLES)
def lab_queue(request):
    awaiting_collection = (LabOrder.objects.filter(status=LabOrder.Status.ORDERED)
                            .select_related('patient', 'ordered_by').order_by('ordered_at'))
    awaiting_result = (LabOrder.objects.filter(status=LabOrder.Status.SAMPLE_COLLECTED)
                        .select_related('patient', 'ordered_by', 'sample').order_by('sample__collected_at'))
    return render(request, 'laboratory/queue.html', {
        'awaiting_collection': awaiting_collection, 'awaiting_result': awaiting_result, 'active_nav': 'laboratory',
    })


@login_required
@role_required(*LAB_ORDER_ROLES)
def order_test(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    if request.method == 'POST':
        form = OrderLabTestForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.patient = patient
            order.ordered_by = request.user
            order.save()
            messages.success(request, f"{order.test_name} ordered for {patient.full_name}.")
            # Not the lab queue: a doctor doesn't have lab access, the same
            # reasoning as pharmacy dispensing redirecting to the patient
            # profile rather than a screen the actor can't open.
            return redirect('patients:detail', pk=patient.pk)
    else:
        form = OrderLabTestForm()
    return render(request, 'laboratory/order_form.html', {'form': form, 'patient': patient, 'active_nav': 'laboratory'})


@login_required
@role_required(*LAB_ROLES)
@require_POST
def collect_sample(request, pk):
    with transaction.atomic():
        order = get_object_or_404(LabOrder.objects.select_for_update(), pk=pk)
        if order.status != LabOrder.Status.ORDERED:
            messages.error(request, "That order is no longer awaiting sample collection.")
        else:
            Sample.objects.create(lab_order=order, collected_by=request.user)
            order.status = LabOrder.Status.SAMPLE_COLLECTED
            order.save(update_fields=['status'])
            messages.success(request, f"Sample collected for {order.test_name} — {order.patient.full_name}.")
    return redirect('laboratory:queue')


@login_required
@role_required(*LAB_ROLES)
def enter_result(request, pk):
    order = get_object_or_404(LabOrder, pk=pk)
    if order.status != LabOrder.Status.SAMPLE_COLLECTED:
        messages.info(request, "That order isn't awaiting a result.")
        return redirect('laboratory:queue')

    if request.method == 'POST':
        form = EnterResultForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    locked = get_object_or_404(LabOrder.objects.select_for_update(), pk=pk)
                    if locked.status != LabOrder.Status.SAMPLE_COLLECTED:
                        raise ValidationError("A result was just entered by someone else.")
                    result = form.save(commit=False)
                    result.lab_order = locked
                    result.entered_by = request.user
                    result.save()
                    locked.status = LabOrder.Status.RESULTED
                    locked.save(update_fields=['status'])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                flag = " (flagged abnormal)" if result.is_abnormal else ""
                messages.success(request, f"Result entered for {order.test_name} — {order.patient.full_name}{flag}.")
                return redirect('laboratory:queue')
    else:
        form = EnterResultForm()
    return render(request, 'laboratory/result_form.html', {'form': form, 'order': order, 'active_nav': 'laboratory'})


@login_required
@role_required(*LAB_ORDER_ROLES)
@require_POST
def cancel_order(request, pk):
    with transaction.atomic():
        order = get_object_or_404(LabOrder.objects.select_for_update(), pk=pk)
        if order.status not in ALLOWED_TRANSITIONS or LabOrder.Status.CANCELLED.value not in ALLOWED_TRANSITIONS.get(order.status, set()):
            messages.error(request, f"An order that is {order.get_status_display().lower()} can't be cancelled.")
        else:
            order.status = LabOrder.Status.CANCELLED
            order.save(update_fields=['status'])
            messages.success(request, f"{order.test_name} for {order.patient.full_name} cancelled.")
    return redirect('patients:detail', pk=order.patient_id)
