import datetime
from django.test import TestCase
from django.urls import reverse

from accounts.models import User, Role
from .models import Patient


class MRNGenerationTests(TestCase):
    def test_mrn_format_and_sequence(self):
        p1 = Patient.objects.create(first_name='A', last_name='One', date_of_birth=datetime.date(1990, 1, 1), gender='M')
        p2 = Patient.objects.create(first_name='B', last_name='Two', date_of_birth=datetime.date(1991, 1, 1), gender='F')
        year = datetime.date.today().year
        self.assertEqual(p1.mrn, f"WCH-{year}-00001")
        self.assertEqual(p2.mrn, f"WCH-{year}-00002")

    def test_mrn_is_not_regenerated_on_resave(self):
        p = Patient.objects.create(first_name='A', last_name='One', date_of_birth=datetime.date(1990, 1, 1), gender='M')
        original_mrn = p.mrn
        p.phone_number = '08000000000'
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.mrn, original_mrn)


class PatientViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='desk', password='pw12345', staff_id='WCH-3001', role=Role.FRONT_DESK)
        self.client.login(username='desk', password='pw12345')
        self.patient = Patient.objects.create(
            first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F', phone_number='08012345678',
        )

    def test_anonymous_cannot_view_patient_list(self):
        self.client.logout()
        response = self.client.get(reverse('patients:list'))
        self.assertEqual(response.status_code, 302)

    def test_patient_list_shows_registered_patient(self):
        response = self.client.get(reverse('patients:list'))
        self.assertContains(response, 'Chidinma')

    def test_patient_list_search_by_name(self):
        Patient.objects.create(first_name='Tunde', last_name='Bakare', date_of_birth=datetime.date(1980, 1, 1), gender='M')
        response = self.client.get(reverse('patients:list'), {'q': 'Tunde'})
        self.assertContains(response, 'Bakare')
        self.assertNotContains(response, 'Chidinma')

    def test_register_patient_creates_record_and_redirects(self):
        response = self.client.post(reverse('patients:register'), {
            'first_name': 'Grace', 'last_name': 'Umeh', 'date_of_birth': '1995-06-01',
            'gender': 'F', 'blood_group': 'O+', 'phone_number': '08099999999', 'email': '', 'address': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Patient.objects.filter(first_name='Grace', last_name='Umeh').exists())

    def test_register_patient_missing_required_field_shows_error(self):
        response = self.client.post(reverse('patients:register'), {'first_name': '', 'last_name': 'Umeh'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')

    def test_patient_detail_shows_mrn_and_blood_group(self):
        response = self.client.get(reverse('patients:detail', args=[self.patient.pk]))
        self.assertContains(response, self.patient.mrn)
        self.assertContains(response, 'Unknown')  # default blood group display
