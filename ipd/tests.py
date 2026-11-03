import datetime
from django.test import TestCase
from django.urls import reverse

from accounts.models import User, Role
from patients.models import Patient
from .models import Ward, Bed, Admission, CarePlan, MedicationAdministration


class IPDAccessControlTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-8001', role=Role.DOCTOR)
        self.nurse = User.objects.create_user(username='nurse', password='pw12345', staff_id='WCH-8002', role=Role.NURSE)
        self.billing = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-8003', role=Role.BILLING)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        ward = Ward.objects.create(name='General')
        self.bed = Bed.objects.create(ward=ward, bed_number='G-01')

    def test_anonymous_redirected_from_bed_map(self):
        response = self.client.get(reverse('ipd:bed_map'))
        self.assertEqual(response.status_code, 302)

    def test_anyone_logged_in_can_view_bed_map(self):
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('ipd:bed_map'))
        self.assertEqual(response.status_code, 200)

    def test_nurse_forbidden_from_admitting(self):
        self.client.login(username='nurse', password='pw12345')
        response = self.client.get(reverse('ipd:admit', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 403)

    def test_billing_forbidden_from_admission_detail(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('ipd:detail', args=[admission.pk]))
        self.assertEqual(response.status_code, 403)

    def test_nurse_can_view_admission_detail(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        self.client.login(username='nurse', password='pw12345')
        response = self.client.get(reverse('ipd:detail', args=[admission.pk]))
        self.assertEqual(response.status_code, 200)


class AdmissionFlowTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-8001', role=Role.DOCTOR)
        self.nurse = User.objects.create_user(username='nurse', password='pw12345', staff_id='WCH-8002', role=Role.NURSE)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.ward = Ward.objects.create(name='General')
        self.bed = Bed.objects.create(ward=self.ward, bed_number='G-01', status=Bed.Status.AVAILABLE)
        self.client.login(username='doc', password='pw12345')

    def test_admitting_marks_bed_occupied(self):
        response = self.client.post(reverse('ipd:admit', args=[self.patient.pk]), {
            'bed': self.bed.pk, 'attending_doctor': self.doctor.pk, 'diagnosis_summary': 'Observation',
        })
        self.assertEqual(response.status_code, 302)
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        self.assertTrue(Admission.objects.filter(patient=self.patient, bed=self.bed, status=Admission.Status.ADMITTED).exists())

    def test_occupied_bed_not_offered_for_new_admission(self):
        self.bed.status = Bed.Status.OCCUPIED
        self.bed.save()
        other_bed = Bed.objects.create(ward=self.ward, bed_number='G-02', status=Bed.Status.AVAILABLE)
        response = self.client.get(reverse('ipd:admit', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.bed.bed_number)
        self.assertContains(response, other_bed.bed_number)

    def test_admitting_with_no_beds_available_redirects_with_error(self):
        self.bed.status = Bed.Status.OCCUPIED
        self.bed.save()
        response = self.client.get(reverse('ipd:admit', args=[self.patient.pk]))
        self.assertEqual(response.status_code, 302)

    def test_care_plan_and_mar_entry_can_be_added(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        url = reverse('ipd:detail', args=[admission.pk])
        self.client.post(url, {'add_care_plan': '1', 'instructions': 'IV fluids 8-hourly'})
        self.assertTrue(CarePlan.objects.filter(admission=admission, instructions='IV fluids 8-hourly').exists())

        self.client.login(username='nurse', password='pw12345')
        self.client.post(url, {'add_mar': '1', 'drug_name': 'Paracetamol', 'dose': '1g'})
        self.assertTrue(MedicationAdministration.objects.filter(admission=admission, drug_name='Paracetamol').exists())

    def test_discharge_frees_the_bed(self):
        self.bed.status = Bed.Status.OCCUPIED
        self.bed.save()
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        response = self.client.post(reverse('ipd:discharge', args=[admission.pk]))
        self.assertEqual(response.status_code, 302)
        admission.refresh_from_db()
        self.bed.refresh_from_db()
        self.assertEqual(admission.status, Admission.Status.DISCHARGED)
        self.assertIsNotNone(admission.discharged_at)
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)

    def test_discharge_requires_post(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        response = self.client.get(reverse('ipd:discharge', args=[admission.pk]))
        self.assertEqual(response.status_code, 405)

    def test_nurse_cannot_discharge(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor)
        self.client.login(username='nurse', password='pw12345')
        response = self.client.post(reverse('ipd:discharge', args=[admission.pk]))
        self.assertEqual(response.status_code, 403)
        admission.refresh_from_db()
        self.assertEqual(admission.status, Admission.Status.ADMITTED)


class BedMapDisplayTests(TestCase):
    def setUp(self):
        self.desk = User.objects.create_user(username='desk', password='pw12345', staff_id='WCH-8004', role=Role.FRONT_DESK)
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-8001', role=Role.DOCTOR)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.ward = Ward.objects.create(name='General')
        self.client.login(username='desk', password='pw12345')

    def test_occupied_bed_shows_patient_name(self):
        bed = Bed.objects.create(ward=self.ward, bed_number='G-01', status=Bed.Status.OCCUPIED)
        Admission.objects.create(patient=self.patient, bed=bed, attending_doctor=self.doctor)
        response = self.client.get(reverse('ipd:bed_map'))
        self.assertContains(response, 'Musa')

    def test_available_count_reflects_bed_statuses(self):
        Bed.objects.create(ward=self.ward, bed_number='G-01', status=Bed.Status.AVAILABLE)
        Bed.objects.create(ward=self.ward, bed_number='G-02', status=Bed.Status.OCCUPIED)
        response = self.client.get(reverse('ipd:bed_map'))
        self.assertEqual(response.context['available'], 1)
        self.assertEqual(response.context['total_beds'], 2)


# ==========================================================================
# Beds and wards management
# ==========================================================================
from .forms import AdmissionForm


class BedManagementTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='adm', password='pw12345', staff_id='WCH-8101', role=Role.ADMIN)
        self.doctor = User.objects.create_user(username='docx', password='pw12345', staff_id='WCH-8102', role=Role.DOCTOR)
        self.ward = Ward.objects.create(name='General')
        self.url = reverse('ipd:manage')
        self.client.login(username='adm', password='pw12345')

    def _beds(self, ward=None):
        return sorted(Bed.objects.filter(ward=ward or self.ward).values_list('bed_number', flat=True))

    def _add_beds(self, numbers, ward=None):
        return self.client.post(self.url, {'add_beds': '1', 'ward': (ward or self.ward).pk, 'bed_numbers': numbers})


class BedManagementAccessTests(BedManagementTestBase):
    def test_administrator_and_superuser_can_open_it(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        User.objects.create_user(username='root', password='pw12345', staff_id='WCH-8103', role=Role.FRONT_DESK, is_superuser=True)
        self.client.login(username='root', password='pw12345')
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_every_other_role_is_refused(self):
        for role in (Role.DOCTOR, Role.NURSE, Role.FRONT_DESK, Role.BILLING, Role.PHARMACIST, Role.LAB_TECH):
            User.objects.create_user(username=f'u_{role}', password='pw12345', staff_id=f'WCH-{role}', role=role)
            self.client.login(username=f'u_{role}', password='pw12345')
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self._add_beds('X-1').status_code, 403)
        self.assertEqual(self._beds(), [])

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)


class AddWardTests(BedManagementTestBase):
    def test_adds_a_ward(self):
        response = self.client.post(self.url, {'add_ward': '1', 'name': '  Paediatrics '})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Ward.objects.filter(name='Paediatrics').exists())

    def test_duplicate_ward_name_is_refused_whatever_the_case(self):
        response = self.client.post(self.url, {'add_ward': '1', 'name': 'general'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Ward.objects.count(), 1)


class AddBedsTests(BedManagementTestBase):
    def test_adds_several_beds_at_once_as_available(self):
        response = self._add_beds('G-10, G-11  G-12\nG-10')  # commas, spaces, newlines, and a repeat
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._beds(), ['G-10', 'G-11', 'G-12'])
        self.assertEqual(set(Bed.objects.values_list('status', flat=True)), {Bed.Status.AVAILABLE})

    def test_all_or_nothing_when_one_already_exists(self):
        Bed.objects.create(ward=self.ward, bed_number='G-01')
        response = self._add_beds('G-01, G-02')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Already in General')
        self.assertEqual(self._beds(), ['G-01'])

    def test_the_same_number_is_fine_in_a_different_ward(self):
        other = Ward.objects.create(name='ICU')
        Bed.objects.create(ward=self.ward, bed_number='01')
        self.assertEqual(self._add_beds('01', ward=other).status_code, 302)
        self.assertEqual(self._beds(other), ['01'])

    def test_rejects_blank_too_long_and_too_many(self):
        for numbers in ('', '   ,  ', 'ABCDEFGHIJK', ', '.join(f'B-{i}' for i in range(51))):
            with self.subTest(numbers=numbers[:20]):
                self.assertEqual(self._add_beds(numbers).status_code, 200)
        self.assertEqual(self._beds(), [])

    def test_new_beds_show_on_the_bed_map(self):
        self._add_beds('G-77')
        self.assertContains(self.client.get(reverse('ipd:bed_map')), 'G-77')


class BedStatusTests(BedManagementTestBase):
    def setUp(self):
        super().setUp()
        self.bed = Bed.objects.create(ward=self.ward, bed_number='G-01')

    def _set(self, status, bed=None):
        return self.client.post(reverse('ipd:bed_status', args=[(bed or self.bed).pk, status]))

    def _status(self, bed=None):
        bed = bed or self.bed
        bed.refresh_from_db()
        return bed.status

    def test_maintenance_round_trip_and_admissions_skip_it(self):
        self._set('MAINTENANCE')
        self.assertEqual(self._status(), Bed.Status.MAINTENANCE)
        self.assertNotIn(self.bed, AdmissionForm().fields['bed'].queryset)
        self._set('AVAILABLE')
        self.assertEqual(self._status(), Bed.Status.AVAILABLE)
        self.assertIn(self.bed, AdmissionForm().fields['bed'].queryset)

    def test_an_occupied_bed_cannot_be_changed(self):
        Bed.objects.filter(pk=self.bed.pk).update(status=Bed.Status.OCCUPIED)
        self._set('MAINTENANCE')
        self.assertEqual(self._status(), Bed.Status.OCCUPIED)

    def test_occupied_cannot_be_set_by_hand(self):
        self._set('OCCUPIED')
        self.assertEqual(self._status(), Bed.Status.AVAILABLE)

    def test_post_only_and_admin_only(self):
        self.assertEqual(self.client.get(reverse('ipd:bed_status', args=[self.bed.pk, 'MAINTENANCE'])).status_code, 405)
        self.client.login(username='docx', password='pw12345')
        self.assertEqual(self._set('MAINTENANCE').status_code, 403)
        self.assertEqual(self._status(), Bed.Status.AVAILABLE)


class BedDeleteTests(BedManagementTestBase):
    def setUp(self):
        super().setUp()
        self.bed = Bed.objects.create(ward=self.ward, bed_number='G-01')
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')

    def _delete(self):
        return self.client.post(reverse('ipd:bed_delete', args=[self.bed.pk]))

    def test_an_unused_bed_can_be_removed(self):
        self._delete()
        self.assertFalse(Bed.objects.filter(pk=self.bed.pk).exists())

    def test_a_bed_with_admission_history_is_kept(self):
        admission = Admission.objects.create(patient=self.patient, bed=self.bed, attending_doctor=self.doctor, status=Admission.Status.DISCHARGED)
        self._delete()
        self.assertTrue(Bed.objects.filter(pk=self.bed.pk).exists())
        admission.refresh_from_db()
        self.assertEqual(admission.bed_id, self.bed.pk)  # the patient's record still points at it

    def test_an_occupied_bed_is_kept(self):
        Bed.objects.filter(pk=self.bed.pk).update(status=Bed.Status.OCCUPIED)
        self._delete()
        self.assertTrue(Bed.objects.filter(pk=self.bed.pk).exists())

    def test_post_only_and_admin_only(self):
        self.assertEqual(self.client.get(reverse('ipd:bed_delete', args=[self.bed.pk])).status_code, 405)
        self.client.login(username='docx', password='pw12345')
        self.assertEqual(self._delete().status_code, 403)
        self.assertTrue(Bed.objects.filter(pk=self.bed.pk).exists())


class ManagePageDisplayTests(BedManagementTestBase):
    def test_shows_who_is_in_an_occupied_bed_and_offers_no_actions_for_it(self):
        bed = Bed.objects.create(ward=self.ward, bed_number='G-01', status=Bed.Status.OCCUPIED)
        patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        Admission.objects.create(patient=patient, bed=bed, attending_doctor=self.doctor)
        response = self.client.get(self.url)
        self.assertContains(response, 'Musa Abdullahi')
        self.assertContains(response, 'Discharge the patient first')
        self.assertNotContains(response, reverse('ipd:bed_delete', args=[bed.pk]))
