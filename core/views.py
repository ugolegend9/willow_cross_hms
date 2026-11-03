from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from appointments.models import Appointment
from billing.models import Payment
from ipd.models import Bed
from patients.models import Patient
from pharmacy.models import Drug
from laboratory.models import LabOrder


@login_required
def dashboard(request):
    # localdate(), not now().date(): the latter is the UTC date, which is
    # still "yesterday" for the first hour of every day in Lagos (UTC+1).
    today = timezone.localdate()
    appointments_today = Appointment.objects.filter(scheduled_for__date=today)
    # Revenue is money actually received today, whenever the invoice was raised.
    revenue_today = Payment.objects.filter(paid_at__date=today).aggregate(total=Sum('amount'))['total'] or 0
    # total_stock/is_low_stock exclude expired batches and aren't simple DB
    # columns, so this is counted in Python rather than with a queryset filter.
    low_stock_count = sum(1 for drug in Drug.objects.prefetch_related('batches') if drug.is_low_stock)
    pending_lab_count = LabOrder.objects.filter(
        status__in=[LabOrder.Status.ORDERED, LabOrder.Status.SAMPLE_COLLECTED],
    ).count()
    return render(request, 'core/dashboard.html', {
        'low_stock_count': low_stock_count,
        'pending_lab_count': pending_lab_count,
        'patients_today': Patient.objects.filter(registered_at__date=today).count(),
        'total_patients': Patient.objects.count(),
        'available_beds': Bed.objects.filter(status=Bed.Status.AVAILABLE).count(),
        'total_beds': Bed.objects.count(),
        'appointments_today_count': appointments_today.count(),
        'todays_appointments': appointments_today.select_related('patient', 'doctor').order_by('scheduled_for')[:6],
        'revenue_today': revenue_today,
        'active_nav': 'dashboard',
    })
