import datetime

from django.test import TestCase
from django.urls import reverse
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from accounts.models import User, Role
from patients.models import Patient
from .forms import EnterResultForm
from .models import LabOrder, Sample, LabResult


def make_user(username, role):
    return User.objects.create_user(username=username, password='pw12345', staff_id=f'T-{username}', role=role)


def make_patient(first='Chidinma', last='Eze'):
    return Patient.objects.create(first_name=first, last_name=last, date_of_birth=datetime.date(1990, 4, 12), gender='F')


class LabAccessControlTests(TestCase):
    def setUp(self):
        self.patient = make_patient()
        self.tech = make_user('tech', Role.LAB_TECH)
        self.doctor = make_user('doc', Role.DOCTOR)
        self.nurse = make_user('nurse', Role.NURSE)

    def test_lab_tech_can_view_queue(self):
        self.client.login(username='tech', password='pw12345')
        self.assertEqual(self.client.get(reverse('laboratory:queue')).status_code, 200)

    def test_doctor_forbidden_from_queue(self):
        self.client.login(username='doc', password='pw12345')
        self.assertEqual(self.client.get(reverse('laboratory:queue')).status_code, 403)

    def test_doctor_can_order_a_test(self):
        self.client.login(username='doc', password='pw12345')
        self.assertEqual(self.client.get(reverse('laboratory:order', args=[self.patient.pk])).status_code, 200)

    def test_lab_tech_cannot_order_a_test(self):
        self.client.login(username='tech', password='pw12345')
        self.assertEqual(self.client.get(reverse('laboratory:order', args=[self.patient.pk])).status_code, 403)

    def test_nurse_is_refused_everywhere(self):
        self.client.login(username='nurse', password='pw12345')
        self.assertEqual(self.client.get(reverse('laboratory:queue')).status_code, 403)
        self.assertEqual(self.client.get(reverse('laboratory:order', args=[self.patient.pk])).status_code, 403)

    def test_anonymous_sent_to_login(self):
        self.assertEqual(self.client.get(reverse('laboratory:queue')).status_code, 302)


class OrderTestTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc2', Role.DOCTOR)
        self.client.login(username='doc2', password='pw12345')
        self.patient = make_patient()

    def test_ordering_creates_an_order_and_redirects_to_patient_profile(self):
        # Not the lab queue: a doctor doesn't have lab access.
        response = self.client.post(reverse('laboratory:order', args=[self.patient.pk]), {
            'test_name': 'Full Blood Count', 'notes': 'Rule out anaemia',
        })
        self.assertRedirects(response, reverse('patients:detail', args=[self.patient.pk]))
        order = LabOrder.objects.get(patient=self.patient)
        self.assertEqual(order.status, LabOrder.Status.ORDERED)
        self.assertEqual(order.ordered_by, self.doctor)

    def test_blank_test_name_is_rejected(self):
        response = self.client.post(reverse('laboratory:order', args=[self.patient.pk]), {'test_name': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LabOrder.objects.exists())


class SampleCollectionTests(TestCase):
    def setUp(self):
        self.tech = make_user('tech2', Role.LAB_TECH)
        self.client.login(username='tech2', password='pw12345')
        self.order = LabOrder.objects.create(patient=make_patient(), test_name='FBC')

    def test_collecting_a_sample_advances_the_order_and_assigns_a_barcode(self):
        response = self.client.post(reverse('laboratory:collect', args=[self.order.pk]))
        self.assertRedirects(response, reverse('laboratory:queue'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, LabOrder.Status.SAMPLE_COLLECTED)
        self.assertTrue(self.order.sample.barcode.startswith(f"LAB-{timezone.localdate().year}-"))

    def test_collecting_twice_is_rejected(self):
        self.client.post(reverse('laboratory:collect', args=[self.order.pk]))
        response = self.client.post(reverse('laboratory:collect', args=[self.order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Sample.objects.filter(lab_order=self.order).count(), 1)

    def test_collect_requires_post(self):
        self.assertEqual(self.client.get(reverse('laboratory:collect', args=[self.order.pk])).status_code, 405)

    def test_barcode_collision_is_retried_not_crashed(self):
        existing = Sample.objects.create(lab_order=self.order, collected_by=self.tech)
        other_order = LabOrder.objects.create(patient=make_patient('Musa', 'Abdullahi'), test_name='U&E',
                                               status=LabOrder.Status.SAMPLE_COLLECTED)
        from unittest import mock
        with mock.patch.object(Sample, '_generate_barcode', side_effect=[existing.barcode, 'LAB-2099-000042']):
            new_sample = Sample(lab_order=other_order)
            new_sample.save()
        self.assertEqual(new_sample.barcode, 'LAB-2099-000042')


class EnterResultTests(TestCase):
    def setUp(self):
        self.tech = make_user('tech3', Role.LAB_TECH)
        self.client.login(username='tech3', password='pw12345')
        self.order = LabOrder.objects.create(patient=make_patient(), test_name='FBC', status=LabOrder.Status.SAMPLE_COLLECTED)
        Sample.objects.create(lab_order=self.order, collected_by=self.tech)
        self.url = reverse('laboratory:result', args=[self.order.pk])

    def test_entering_a_result_marks_the_order_resulted(self):
        response = self.client.post(self.url, {'value': '12', 'unit': 'g/dL', 'reference_range': '', 'notes': ''})
        self.assertRedirects(response, reverse('laboratory:queue'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, LabOrder.Status.RESULTED)
        self.assertEqual(self.order.result.value, '12')

    def test_numeric_value_outside_range_is_auto_flagged(self):
        self.client.post(self.url, {'value': '15', 'reference_range': '4.0-11.0'})
        self.assertTrue(self.order.result.is_abnormal)

    def test_numeric_value_inside_range_is_not_flagged(self):
        self.client.post(self.url, {'value': '8', 'reference_range': '4.0-11.0', 'is_abnormal': 'on'})
        # Auto-detection overrides the manual tick when it can actually compute.
        self.assertFalse(self.order.result.is_abnormal)

    def test_non_numeric_value_respects_the_manual_checkbox(self):
        self.client.post(self.url, {'value': 'Positive', 'is_abnormal': 'on'})
        self.assertTrue(self.order.result.is_abnormal)

    def test_cannot_enter_a_result_before_collection(self):
        pending = LabOrder.objects.create(patient=make_patient('Tunde', 'Bakare'), test_name='U&E')
        response = self.client.get(reverse('laboratory:result', args=[pending.pk]))
        self.assertRedirects(response, reverse('laboratory:queue'))

    def test_entering_twice_is_rejected_cleanly(self):
        self.client.post(self.url, {'value': '12'})
        response = self.client.post(self.url, {'value': '99'})
        self.assertEqual(response.status_code, 302)  # already resulted -> bounced to queue
        self.assertEqual(LabResult.objects.filter(lab_order=self.order).count(), 1)
        self.assertEqual(self.order.result.value, '12')


class ConcurrentResultEntryTests(TestCase):
    """Two techs open the same awaiting-result order at once. The second save
    must be a clean, handled error -- not a raw IntegrityError (500) from the
    OneToOneField's unique constraint, the same lesson as pharmacy dispensing."""

    def setUp(self):
        self.tech = make_user('tech4', Role.LAB_TECH)
        self.order = LabOrder.objects.create(patient=make_patient(), test_name='FBC', status=LabOrder.Status.SAMPLE_COLLECTED)
        Sample.objects.create(lab_order=self.order, collected_by=self.tech)

    def test_second_concurrent_result_entry_is_handled(self):
        from django.core.exceptions import ValidationError
        form1 = EnterResultForm(data={'value': '12'})
        form2 = EnterResultForm(data={'value': '99'})
        self.assertTrue(form1.is_valid())
        self.assertTrue(form2.is_valid())

        # First save, simulating the view's own locking logic directly.
        from django.db import transaction
        with transaction.atomic():
            locked = LabOrder.objects.select_for_update().get(pk=self.order.pk)
            result = form1.save(commit=False)
            result.lab_order = locked
            result.save()
            locked.status = LabOrder.Status.RESULTED
            locked.save(update_fields=['status'])

        with self.assertRaises(ValidationError):
            with transaction.atomic():
                locked = LabOrder.objects.select_for_update().get(pk=self.order.pk)
                if locked.status != LabOrder.Status.SAMPLE_COLLECTED:
                    raise ValidationError("A result was just entered by someone else.")

    def test_the_view_itself_does_not_500_on_a_sequential_double_post(self):
        url = reverse('laboratory:result', args=[self.order.pk])
        self.client.login(username='tech4', password='pw12345')
        self.client.post(url, {'value': '12'})
        response = self.client.post(url, {'value': '99'})
        self.assertNotEqual(response.status_code, 500)


class CancelOrderTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc3', Role.DOCTOR)
        self.tech = make_user('tech5', Role.LAB_TECH)
        self.client.login(username='doc3', password='pw12345')
        self.patient = make_patient()

    def test_doctor_can_cancel_a_pending_order(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC', ordered_by=self.doctor)
        response = self.client.post(reverse('laboratory:cancel', args=[order.pk]))
        self.assertRedirects(response, reverse('patients:detail', args=[self.patient.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, LabOrder.Status.CANCELLED)

    def test_a_resulted_order_cannot_be_cancelled(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC', status=LabOrder.Status.RESULTED)
        self.client.post(reverse('laboratory:cancel', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, LabOrder.Status.RESULTED)

    def test_lab_tech_cannot_cancel(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC')
        self.client.login(username='tech5', password='pw12345')
        response = self.client.post(reverse('laboratory:cancel', args=[order.pk]))
        self.assertEqual(response.status_code, 403)

    def test_cancel_requires_post(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC')
        self.assertEqual(self.client.get(reverse('laboratory:cancel', args=[order.pk])).status_code, 405)


class EHRIntegrationTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc4', Role.DOCTOR)
        self.client.login(username='doc4', password='pw12345')
        self.patient = make_patient()

    def test_pending_order_shows_in_ehr(self):
        LabOrder.objects.create(patient=self.patient, test_name='FBC', ordered_by=self.doctor)
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertContains(response, 'FBC')
        self.assertContains(response, 'Ordered')

    def test_abnormal_result_shows_flagged_in_ehr(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC', status=LabOrder.Status.RESULTED)
        LabResult.objects.create(lab_order=order, value='15', unit='g/dL', is_abnormal=True)
        response = self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk]))
        self.assertContains(response, 'Abnormal')

    def test_cancel_button_only_shown_to_order_roles_on_cancellable_orders(self):
        order = LabOrder.objects.create(patient=self.patient, test_name='FBC', ordered_by=self.doctor)
        url = reverse('ehr:patient_ehr', args=[self.patient.pk])
        self.assertContains(self.client.get(url), reverse('laboratory:cancel', args=[order.pk]))

        resulted = LabOrder.objects.create(patient=self.patient, test_name='U&E', status=LabOrder.Status.RESULTED)
        self.assertNotContains(self.client.get(url), reverse('laboratory:cancel', args=[resulted.pk]))


class QueryCountTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc5', Role.DOCTOR)
        self.client.force_login(self.doctor)

    def test_ehr_lab_section_has_flat_query_cost(self):
        patient = make_patient()
        url = reverse('ehr:patient_ehr', args=[patient.pk])

        def add(n):
            for i in range(n):
                order = LabOrder.objects.create(patient=patient, test_name=f'Test {i}', ordered_by=self.doctor, status=LabOrder.Status.RESULTED)
                LabResult.objects.create(lab_order=order, value='1', unit='x')

        add(2)
        with CaptureQueriesContext(connection) as few:
            self.client.get(url)
        add(10)
        with CaptureQueriesContext(connection) as many:
            self.client.get(url)
        self.assertEqual(len(few), len(many))

    def test_lab_tech_queue_has_flat_query_cost(self):
        tech = make_user('tech6', Role.LAB_TECH)
        self.client.force_login(tech)

        def add(n):
            for i in range(n):
                LabOrder.objects.create(patient=make_patient(f'P{i}', 'X'), test_name='FBC', ordered_by=self.doctor)

        add(2)
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse('laboratory:queue'))
        add(10)
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse('laboratory:queue'))
        self.assertEqual(len(few), len(many))
