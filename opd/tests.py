import datetime
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from patients.models import Patient
from ehr.models import Encounter
from appointments.models import Appointment
from .forms import OPDVisitForm
from .models import OPDVisit, Prescription, Referral


class OPDAccessControlTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-7001', role=Role.DOCTOR)
        self.nurse = User.objects.create_user(username='nurse', password='pw12345', staff_id='WCH-7002', role=Role.NURSE)

    def test_doctor_can_open_consult_form(self):
        self.client.login(username='doc', password='pw12345')
        response = self.client.get(reverse('opd:consult', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 200)

    def test_nurse_forbidden_from_consult(self):
        self.client.login(username='nurse', password='pw12345')
        response = self.client.get(reverse('opd:consult', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 403)

    def test_anyone_logged_in_can_view_queue(self):
        self.client.login(username='nurse', password='pw12345')
        response = self.client.get(reverse('opd:queue'))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected_from_queue(self):
        response = self.client.get(reverse('opd:queue'))
        self.assertEqual(response.status_code, 302)


class OPDQueueTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-7001', role=Role.DOCTOR)
        self.desk = User.objects.create_user(username='desk', password='pw12345', staff_id='WCH-7003', role=Role.FRONT_DESK)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.client.login(username='desk', password='pw12345')

    def test_checked_in_appointment_appears_in_queue(self):
        Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN)
        response = self.client.get(reverse('opd:queue'))
        self.assertContains(response, 'Musa')

    def test_scheduled_but_not_checked_in_does_not_appear(self):
        Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.SCHEDULED)
        response = self.client.get(reverse('opd:queue'))
        self.assertContains(response, 'No one checked in yet')


class OPDConsultationTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-7001', role=Role.DOCTOR)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.client.login(username='doc', password='pw12345')

    def test_consultation_creates_visit_and_linked_encounter(self):
        response = self.client.post(reverse('opd:consult', args=[self.patient.pk]), {'chief_complaint': 'Headache'})
        self.assertEqual(response.status_code, 302)
        visit = OPDVisit.objects.get(patient=self.patient)
        self.assertEqual(visit.doctor, self.doctor)
        self.assertIsNotNone(visit.encounter)
        self.assertTrue(Encounter.objects.filter(patient=self.patient, reason='Headache').exists())

    def test_prescription_created_when_drug_fully_specified(self):
        self.client.post(reverse('opd:consult', args=[self.patient.pk]), {
            'chief_complaint': 'Cough', 'drug_name': 'Amoxicillin', 'dosage': '250mg',
            'frequency': '3x daily', 'duration_days': '5',
        })
        visit = OPDVisit.objects.get(patient=self.patient)
        self.assertEqual(Prescription.objects.get(opd_visit=visit).drug_name, 'Amoxicillin')

    def test_partial_prescription_is_rejected(self):
        response = self.client.post(reverse('opd:consult', args=[self.patient.pk]), {
            'chief_complaint': 'Cough', 'drug_name': 'Amoxicillin',  # missing dosage/frequency/duration
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dosage, frequency, and duration')
        self.assertFalse(OPDVisit.objects.filter(patient=self.patient).exists())

    def test_referral_without_reason_is_rejected(self):
        response = self.client.post(reverse('opd:consult', args=[self.patient.pk]), {
            'chief_complaint': 'Chest pain', 'referral_department': 'Cardiology',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'referral needs a reason')

    def test_referral_created_with_reason(self):
        self.client.post(reverse('opd:consult', args=[self.patient.pk]), {
            'chief_complaint': 'Chest pain', 'referral_department': 'Cardiology', 'referral_reason': 'Suspected arrhythmia',
        })
        visit = OPDVisit.objects.get(patient=self.patient)
        self.assertEqual(Referral.objects.get(opd_visit=visit).to_department, 'Cardiology')

    def test_consult_from_appointment_marks_it_completed(self):
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN,
        )
        self.client.post(reverse('opd:consult_from_appointment', args=[self.patient.pk, appt.pk]), {'chief_complaint': 'Follow-up'})
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.COMPLETED)

    def test_an_already_completed_appointment_cannot_be_consulted_again(self):
        """Same bug class as pharmacy double-dispense and lab double-result,
        caught in a later audit: nothing stopped a second OPDVisit (and a
        second Encounter, and a second Prescription) being created for an
        appointment that was already consulted -- a stale tab, a double
        click, or the browser's back button were all enough."""
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.COMPLETED,
        )
        self.client.post(reverse('opd:consult_from_appointment', args=[self.patient.pk, appt.pk]), {
            'chief_complaint': 'Follow-up', 'drug_name': 'Amoxicillin', 'dosage': '250mg', 'frequency': '3x daily', 'duration_days': '5',
        })
        self.assertFalse(OPDVisit.objects.filter(patient=self.patient).exists())
        self.assertFalse(Encounter.objects.filter(patient=self.patient).exists())

    def test_a_cancelled_appointment_cannot_be_consulted(self):
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CANCELLED,
        )
        self.client.post(reverse('opd:consult_from_appointment', args=[self.patient.pk, appt.pk]), {'chief_complaint': 'Walk-in'})
        self.assertFalse(OPDVisit.objects.exists())

    def test_sequential_double_post_only_creates_one_visit(self):
        """The ordinary case: by the time the second request arrives, the
        first has already committed, so the view's own pre-check (fetching
        fresh status) catches it. See ConcurrentConsultTests below for the
        narrower race this doesn't cover."""
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN,
        )
        url = reverse('opd:consult_from_appointment', args=[self.patient.pk, appt.pk])
        self.client.post(url, {'chief_complaint': 'First consult'})
        self.client.post(url, {'chief_complaint': 'Second consult (should be refused)'})
        self.assertEqual(OPDVisit.objects.filter(patient=self.patient).count(), 1)
        self.assertEqual(OPDVisit.objects.get(patient=self.patient).chief_complaint, 'First consult')

    def test_prescription_appears_in_patient_ehr_timeline(self):
        self.client.post(reverse('opd:consult', args=[self.patient.pk]), {
            'chief_complaint': 'Cough', 'drug_name': 'Amoxicillin', 'dosage': '250mg',
            'frequency': '3x daily', 'duration_days': '5',
        })
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertContains(response, 'Amoxicillin')


class ConcurrentConsultTests(TestCase):
    """Two doctors open the same checked-in appointment at once -- both pass
    the view's pre-check before either commits. This bypasses the view
    entirely to exercise OPDVisitForm.save()'s own lock directly, the same
    way pharmacy's DispenseForm and lab's result entry are tested, since a
    real race can't be produced through two sequential test-client requests
    (the first always fully commits before the second even starts)."""

    def setUp(self):
        self.doctor = User.objects.create_user(username='doc9', password='pw12345', staff_id='WCH-9901', role=Role.DOCTOR)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN,
        )

    def test_second_concurrent_save_is_a_clean_error_not_a_duplicate_or_a_crash(self):
        form1 = OPDVisitForm(data={'chief_complaint': 'First'})
        form2 = OPDVisitForm(data={'chief_complaint': 'Second'})
        self.assertTrue(form1.is_valid())
        self.assertTrue(form2.is_valid())

        form1.save(self.patient, self.doctor, self.appointment)
        with self.assertRaises(ValidationError):
            form2.save(self.patient, self.doctor, self.appointment)

        self.assertEqual(OPDVisit.objects.filter(patient=self.patient).count(), 1)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.COMPLETED)
