import datetime
from django.test import TestCase
from django.urls import reverse

from accounts.models import User, Role
from patients.models import Patient
from .models import Encounter, Vitals, Diagnosis, Allergy


class EHRAccessControlTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F')
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-4001', role=Role.DOCTOR)
        self.billing = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-4002', role=Role.BILLING)

    def test_doctor_can_view_ehr(self):
        self.client.login(username='doc', password='pw12345')
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 200)

    def test_billing_officer_forbidden_from_ehr(self):
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 302)


class EncounterFormTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F')
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-4001', role=Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        self.url = reverse('ehr:patient_ehr', args=[self.patient.pk])

    def test_full_encounter_creates_linked_vitals_and_diagnosis(self):
        response = self.client.post(self.url, {
            'add_encounter': '1', 'reason': 'Routine checkup', 'temperature_c': '37.2',
            'blood_pressure': '118/76', 'pulse_bpm': '80', 'spo2_percent': '98',
            'diagnosis': 'Normal findings', 'note': 'All good.',
        })
        self.assertEqual(response.status_code, 302)
        encounter = Encounter.objects.get(patient=self.patient)
        self.assertEqual(encounter.clinician, self.doctor)
        self.assertEqual(Vitals.objects.get(encounter=encounter).pulse_bpm, 80)
        self.assertEqual(Diagnosis.objects.get(encounter=encounter).description, 'Normal findings')

    def test_encounter_without_vitals_skips_vitals_row(self):
        self.client.post(self.url, {'add_encounter': '1', 'reason': 'Quick question, no exam'})
        encounter = Encounter.objects.get(patient=self.patient)
        self.assertFalse(Vitals.objects.filter(encounter=encounter).exists())

    def test_missing_reason_shows_validation_error(self):
        response = self.client.post(self.url, {'add_encounter': '1', 'reason': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(Encounter.objects.filter(patient=self.patient).exists())

    def test_add_allergy_shows_banner(self):
        response = self.client.post(self.url, {'add_allergy': '1', 'substance': 'Penicillin', 'reaction': 'Rash', 'severity': 'SEVERE'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Allergy.objects.filter(patient=self.patient, substance='Penicillin').exists())
        page = self.client.get(self.url)
        self.assertContains(page, 'Penicillin')
        self.assertContains(page, 'Allergies')
