import datetime
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from patients.models import Patient
from .models import Appointment


class AppointmentAccessControlTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-5001', role=Role.DOCTOR)
        self.billing = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-5002', role=Role.BILLING)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')

    def test_billing_officer_forbidden_from_booking(self):
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('appointments:create'))
        self.assertEqual(response.status_code, 403)

    def test_billing_officer_can_still_view_list(self):
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('appointments:list'))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected_from_list(self):
        response = self.client.get(reverse('appointments:list'))
        self.assertEqual(response.status_code, 302)


class AppointmentBookingAndStatusTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-5001', role=Role.DOCTOR)
        self.desk = User.objects.create_user(username='desk', password='pw12345', staff_id='WCH-5003', role=Role.FRONT_DESK)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.client.login(username='desk', password='pw12345')

    def test_booking_creates_appointment(self):
        when = (timezone.now() + datetime.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(reverse('appointments:create'), {
            'patient': self.patient.pk, 'doctor': self.doctor.pk, 'scheduled_for': when,
            'department': 'General', 'notes': 'Follow-up',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Appointment.objects.filter(patient=self.patient, doctor=self.doctor).exists())

    def test_new_appointment_defaults_to_scheduled(self):
        appt = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now())
        self.assertEqual(appt.status, Appointment.Status.SCHEDULED)

    def test_status_flow_scheduled_to_checked_in_to_completed(self):
        appt = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now())

        self.client.post(reverse('appointments:set_status', args=[appt.pk, 'CHECKED_IN']))
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CHECKED_IN)

        self.client.post(reverse('appointments:set_status', args=[appt.pk, 'COMPLETED']))
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.COMPLETED)

    def test_status_change_rejects_get(self):
        """Regression guard: this used to be a plain GET link, which is
        CSRF-unsafe for a state-changing action."""
        appt = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now())
        response = self.client.get(reverse('appointments:set_status', args=[appt.pk, 'CHECKED_IN']))
        self.assertEqual(response.status_code, 405)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.SCHEDULED)

    def test_invalid_status_value_is_ignored(self):
        appt = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now())
        self.client.post(reverse('appointments:set_status', args=[appt.pk, 'NOT_A_REAL_STATUS']))
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.SCHEDULED)

    def test_scope_filters(self):
        past = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now() - datetime.timedelta(days=1))
        future = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now() + datetime.timedelta(days=1))

        def ids(scope):
            response = self.client.get(reverse('appointments:list'), {'scope': scope})
            return {a.pk for a in response.context['appointments']}

        self.assertEqual(ids('upcoming'), {future.pk})
        self.assertEqual(ids('past'), {past.pk})
