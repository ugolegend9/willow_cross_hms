from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.permissions import BOOKING_ROLES
from .forms import AppointmentForm
from .models import Appointment

_S = Appointment.Status
# The status flow is enforced here, on the server. Hiding a button in the
# template is not a control: anyone can POST to this URL directly.
ALLOWED_TRANSITIONS = {
    _S.SCHEDULED.value: {_S.CHECKED_IN.value, _S.CANCELLED.value, _S.NO_SHOW.value},
    _S.CHECKED_IN.value: {_S.COMPLETED.value, _S.CANCELLED.value},
}


@login_required
def appointment_list(request):
    scope = request.GET.get('scope', 'upcoming')
    qs = Appointment.objects.select_related('patient', 'doctor')
    now = timezone.now()
    if scope == 'today':
        qs = qs.filter(scheduled_for__date=timezone.localdate())
    elif scope == 'past':
        qs = qs.filter(scheduled_for__lt=now)
    else:
        qs = qs.filter(scheduled_for__gte=now)
    return render(request, 'appointments/appointment_list.html', {
        'appointments': qs[:200],
        'scope': scope,
        'active_nav': 'appointments',
    })


@login_required
@role_required(*BOOKING_ROLES)
def appointment_create(request):
    if request.method == 'POST':
        form = AppointmentForm(request.POST)
        if form.is_valid():
            appt = form.save()
            messages.success(request, f"Appointment booked for {appt.patient.full_name} on {appt.scheduled_for:%d %b %Y %H:%M}.")
            return redirect('appointments:list')
    else:
        form = AppointmentForm()
    return render(request, 'appointments/appointment_form.html', {'form': form, 'active_nav': 'appointments'})


@login_required
@role_required(*BOOKING_ROLES)
@require_POST
def appointment_set_status(request, pk, status):
    appt = get_object_or_404(Appointment, pk=pk)
    labels = dict(Appointment.Status.choices)

    if status not in labels:
        messages.error(request, "Unknown appointment status.")
    elif status not in ALLOWED_TRANSITIONS.get(appt.status, set()):
        messages.error(request, f"An appointment that is {labels[appt.status].lower()} can't be marked {labels[status].lower()}.")
    else:
        appt.status = status
        appt.save(update_fields=['status'])
        messages.success(request, f"{appt.patient.full_name}'s appointment marked {labels[status]}.")

    # Only bounce back to the referring page if it is on this site; an
    # unchecked Referer would make this an open redirect.
    referer = request.META.get('HTTP_REFERER')
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(referer)
    return redirect('appointments:list')
