import datetime
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from patients.models import Patient
from ipd.models import Ward, Bed
from appointments.models import Appointment
from billing.models import Invoice, LineItem, Payment


class DashboardTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-6001', role=Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_loads_with_no_data(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Good day')

    def test_dashboard_counts_reflect_seeded_data(self):
        patient = Patient.objects.create(first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F')
        ward = Ward.objects.create(name='Maternity')
        Bed.objects.create(ward=ward, bed_number='M-01', status=Bed.Status.AVAILABLE)
        Bed.objects.create(ward=ward, bed_number='M-02', status=Bed.Status.OCCUPIED)
        Appointment.objects.create(patient=patient, doctor=self.doctor, scheduled_for=timezone.now())
        invoice = Invoice.objects.create(patient=patient)
        LineItem.objects.create(invoice=invoice, description='Consultation', amount=15000)
        Payment.objects.create(invoice=invoice, amount=15000, method=Payment.Method.CASH)

        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['patients_today'], 1)
        self.assertEqual(response.context['available_beds'], 1)
        self.assertEqual(response.context['total_beds'], 2)
        self.assertEqual(len(response.context['todays_appointments']), 1)
        self.assertEqual(response.context['revenue_today'], 15000)

    def test_quick_action_links_present_for_this_users_role(self):
        # self.doctor can book appointments but, per accounts.permissions,
        # cannot register patients -- see PatientRegistrationAccessTests for
        # the full per-role matrix.
        response = self.client.get(reverse('core:dashboard'))
        self.assertContains(response, reverse('appointments:create'))
        self.assertNotContains(response, reverse('patients:register'))
