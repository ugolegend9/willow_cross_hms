from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.decorators import role_required
from accounts.permissions import ADMIT_ROLES, BED_MANAGEMENT_ROLES, IPD_CLINICAL_ROLES
from patients.models import Patient
from .models import Ward, Bed, Admission
from .forms import AddBedsForm, AdmissionForm, CarePlanForm, MedicationAdministrationForm, WardForm


def _occupants():
    """{bed_id: active Admission}, in one query instead of one per occupied bed."""
    return {a.bed_id: a for a in Admission.objects
            .filter(status=Admission.Status.ADMITTED, bed__isnull=False)
            .select_related('patient').order_by('admitted_at')}


@login_required
def bed_map(request):
    occupants = _occupants()
    wards = Ward.objects.prefetch_related(Prefetch('beds', queryset=Bed.objects.order_by('bed_number'))).order_by('name')
    ward_data = [
        {'ward': ward, 'beds': [
            {'bed': bed, 'admission': occupants.get(bed.pk) if bed.status == Bed.Status.OCCUPIED else None}
            for bed in ward.beds.all()
        ]}
        for ward in wards
    ]
    total_beds = Bed.objects.count()
    available = Bed.objects.filter(status=Bed.Status.AVAILABLE).count()
    return render(request, 'ipd/bed_map.html', {
        'ward_data': ward_data, 'total_beds': total_beds, 'available': available, 'active_nav': 'ipd',
    })


@login_required
@role_required(*ADMIT_ROLES)
def admit_patient(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    current = Admission.objects.filter(patient=patient, status=Admission.Status.ADMITTED).select_related('bed__ward').first()
    if current:
        messages.error(request, f"{patient.full_name} is already admitted ({current.bed}).")
        return redirect('ipd:detail', pk=current.pk)
    if not Bed.objects.filter(status=Bed.Status.AVAILABLE).exists():
        messages.error(request, "No beds are currently available.")
        return redirect('patients:detail', pk=patient.pk)

    if request.method == 'POST':
        form = AdmissionForm(request.POST)
        if form.is_valid():
            try:
                admission = form.save(patient)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"{patient.full_name} admitted to {admission.bed}.")
                return redirect('ipd:detail', pk=admission.pk)
    else:
        form = AdmissionForm()
    return render(request, 'ipd/admit_form.html', {'form': form, 'patient': patient, 'active_nav': 'ipd'})


@login_required
@role_required(*IPD_CLINICAL_ROLES)
def admission_detail(request, pk):
    admission = get_object_or_404(Admission, pk=pk)
    care_plan_form = CarePlanForm()
    mar_form = MedicationAdministrationForm()

    if request.method == 'POST':
        if 'add_care_plan' in request.POST:
            care_plan_form = CarePlanForm(request.POST)
            if care_plan_form.is_valid():
                plan = care_plan_form.save(commit=False)
                plan.admission = admission
                plan.created_by = request.user
                plan.save()
                return redirect('ipd:detail', pk=pk)
        elif 'add_mar' in request.POST:
            mar_form = MedicationAdministrationForm(request.POST)
            if mar_form.is_valid():
                entry = mar_form.save(commit=False)
                entry.admission = admission
                entry.administered_by = request.user
                entry.save()
                return redirect('ipd:detail', pk=pk)

    return render(request, 'ipd/admission_detail.html', {
        'admission': admission,
        'care_plans': admission.care_plans.select_related('created_by').order_by('-created_at'),
        'mar_entries': admission.mar_entries.select_related('administered_by').order_by('-administered_at'),
        'care_plan_form': care_plan_form,
        'mar_form': mar_form,
        'active_nav': 'ipd',
    })


@login_required
@role_required(*ADMIT_ROLES)
@require_POST
def discharge_admission(request, pk):
    admission = get_object_or_404(Admission, pk=pk)
    if admission.status == Admission.Status.ADMITTED:
        admission.status = Admission.Status.DISCHARGED
        admission.discharged_at = timezone.now()
        admission.save(update_fields=['status', 'discharged_at'])
        if admission.bed:
            admission.bed.status = Bed.Status.AVAILABLE
            admission.bed.save(update_fields=['status'])
        messages.success(request, f"{admission.patient.full_name} discharged.")
    return redirect('ipd:detail', pk=pk)


@login_required
@role_required(*BED_MANAGEMENT_ROLES)
def manage_beds(request):
    ward_form, beds_form = WardForm(), AddBedsForm()

    if request.method == 'POST':
        if 'add_ward' in request.POST:
            ward_form = WardForm(request.POST)
            if ward_form.is_valid():
                ward = ward_form.save()
                messages.success(request, f"Ward “{ward.name}” added. You can add beds to it now.")
                return redirect('ipd:manage')
        elif 'add_beds' in request.POST:
            beds_form = AddBedsForm(request.POST)
            if beds_form.is_valid():
                try:
                    created = beds_form.save()
                except IntegrityError:  # someone else added the same number a moment ago
                    beds_form.add_error(None, "Some of those beds were just added by someone else. Check the list and try again.")
                else:
                    ward = beds_form.cleaned_data['ward']
                    messages.success(request, f"Added {len(created)} bed{'s' if len(created) != 1 else ''} to {ward.name}.")
                    return redirect('ipd:manage')

    occupants = _occupants()
    wards = Ward.objects.prefetch_related(Prefetch(
        'beds', queryset=Bed.objects.annotate(admission_count=Count('admissions')).order_by('bed_number'),
    )).order_by('name')
    ward_data = [
        {'ward': ward, 'beds': [
            {'bed': bed, 'admission': occupants.get(bed.pk) if bed.status == Bed.Status.OCCUPIED else None}
            for bed in ward.beds.all()
        ]}
        for ward in wards
    ]
    return render(request, 'ipd/manage.html', {
        'ward_form': ward_form, 'beds_form': beds_form, 'ward_data': ward_data, 'active_nav': 'ipd',
    })


@login_required
@role_required(*BED_MANAGEMENT_ROLES)
@require_POST
def bed_set_status(request, pk, status):
    # Only these two can be set by hand. "Occupied" is set by admitting a patient.
    if status not in (Bed.Status.AVAILABLE.value, Bed.Status.MAINTENANCE.value):
        messages.error(request, "A bed can only be set to Available or Maintenance here. Admitting a patient is what occupies a bed.")
        return redirect('ipd:manage')
    with transaction.atomic():
        bed = get_object_or_404(Bed.objects.select_for_update(), pk=pk)
        if bed.status == Bed.Status.OCCUPIED:
            messages.error(request, f"{bed} is occupied. Discharge the patient first.")
        else:
            bed.status = status
            bed.save(update_fields=['status'])
            messages.success(request, f"{bed} is now {bed.get_status_display().lower()}.")
    return redirect('ipd:manage')


@login_required
@role_required(*BED_MANAGEMENT_ROLES)
@require_POST
def bed_delete(request, pk):
    with transaction.atomic():
        bed = get_object_or_404(Bed.objects.select_for_update(), pk=pk)
        if bed.status == Bed.Status.OCCUPIED:
            messages.error(request, f"{bed} is occupied and can't be removed.")
        elif bed.admissions.exists():
            # Deleting it would detach it from those patients' records.
            messages.error(request, f"{bed} has admission history, so it can't be removed. Mark it as under maintenance to take it out of use.")
        else:
            label = str(bed)
            bed.delete()
            messages.success(request, f"{label} removed.")
    return redirect('ipd:manage')
