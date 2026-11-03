"""
Regression tests for problems found while auditing the build.

Each class pins down one real bug so it can't quietly come back.
"""
import datetime
from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from appointments.models import Appointment
from billing.models import Invoice, LineItem, Payment
from ehr.models import Encounter
from ipd.forms import AdmissionForm
from ipd.models import Ward, Bed, Admission
from opd.models import OPDVisit
from patients.models import Patient


def make_user(username, role, **extra):
    return User.objects.create_user(username=username, password='pw12345', staff_id=f'T-{username}', role=role, **extra)


def make_patient(first='Chidinma', last='Eze'):
    return Patient.objects.create(first_name=first, last_name=last, date_of_birth=datetime.date(1990, 4, 12), gender='F')


# --------------------------------------------------------------------------
# Dashboard revenue: must be money *received* today, not "payments on
# invoices that happened to be created today".
# --------------------------------------------------------------------------
class DashboardRevenueTests(TestCase):
    def setUp(self):
        make_user('bill', Role.BILLING)
        self.client.login(username='bill', password='pw12345')
        self.patient = make_patient()

    def _invoice(self, total='10000'):
        invoice = Invoice.objects.create(patient=self.patient)
        LineItem.objects.create(invoice=invoice, description='Care', amount=total)
        return invoice

    def test_payment_today_on_an_older_invoice_counts_as_todays_revenue(self):
        invoice = self._invoice()
        Invoice.objects.filter(pk=invoice.pk).update(created_at=timezone.now() - datetime.timedelta(days=3))
        Payment.objects.create(invoice=invoice, amount=4000, method=Payment.Method.CASH)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['revenue_today'], 4000)

    def test_old_payment_on_a_new_invoice_is_not_todays_revenue(self):
        invoice = self._invoice()
        payment = Payment.objects.create(invoice=invoice, amount=4000, method=Payment.Method.CASH)
        Payment.objects.filter(pk=payment.pk).update(paid_at=timezone.now() - datetime.timedelta(days=2))
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['revenue_today'], 0)


# --------------------------------------------------------------------------
# "Today" must mean today in Africa/Lagos, not today in UTC. Lagos is UTC+1,
# so for the first hour of every local day the two dates disagree.
# --------------------------------------------------------------------------
class LocalDateTests(TestCase):
    # 23:30 UTC on the 28th == 00:30 on the 29th in Lagos
    FIXED_NOW = datetime.datetime(2026, 9, 28, 23, 30, tzinfo=datetime.timezone.utc)

    def setUp(self):
        patcher = mock.patch('django.utils.timezone.now', return_value=self.FIXED_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.doctor = make_user('doc', Role.DOCTOR)
        self.client.force_login(self.doctor)
        self.patient = make_patient()
        # 09:00 Lagos on the 29th
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, status=Appointment.Status.CHECKED_IN,
            scheduled_for=datetime.datetime(2026, 9, 29, 8, 0, tzinfo=datetime.timezone.utc),
        )

    def test_dashboard_today_is_local_today(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(len(response.context['todays_appointments']), 1)

    def test_appointment_today_filter_is_local_today(self):
        response = self.client.get(reverse('appointments:list'), {'scope': 'today'})
        self.assertContains(response, 'Chidinma')

    def test_opd_queue_is_local_today(self):
        response = self.client.get(reverse('opd:queue'))
        self.assertContains(response, 'Chidinma')


# --------------------------------------------------------------------------
# OPD: a consultation started "from an appointment" must belong to that patient.
# --------------------------------------------------------------------------
class OPDAppointmentMismatchTests(TestCase):
    def test_appointment_for_a_different_patient_is_rejected(self):
        doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        patient_a, patient_b = make_patient('Ada', 'One'), make_patient('Bola', 'Two')
        appt = Appointment.objects.create(
            patient=patient_a, doctor=doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN,
        )
        response = self.client.post(
            reverse('opd:consult_from_appointment', args=[patient_b.pk, appt.pk]), {'chief_complaint': 'Cough'},
        )
        self.assertEqual(response.status_code, 404)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CHECKED_IN)
        self.assertFalse(OPDVisit.objects.exists())
        self.assertFalse(Encounter.objects.exists())


# --------------------------------------------------------------------------
# IPD: no double admissions, no double-booked beds.
# --------------------------------------------------------------------------
class AdmissionGuardTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        self.patient = make_patient()
        ward = Ward.objects.create(name='General')
        self.bed1 = Bed.objects.create(ward=ward, bed_number='G-01')
        self.bed2 = Bed.objects.create(ward=ward, bed_number='G-02')

    def _admit(self, bed):
        return self.client.post(reverse('ipd:admit', args=[self.patient.pk]), {
            'bed': bed.pk, 'attending_doctor': self.doctor.pk, 'diagnosis_summary': 'Observation',
        })

    def test_an_already_admitted_patient_cannot_be_admitted_again(self):
        self._admit(self.bed1)
        self._admit(self.bed2)
        self.assertEqual(Admission.objects.filter(patient=self.patient, status=Admission.Status.ADMITTED).count(), 1)
        self.bed2.refresh_from_db()
        self.assertEqual(self.bed2.status, Bed.Status.AVAILABLE)

    def test_bed_taken_between_validation_and_save_is_refused(self):
        form = AdmissionForm(data={'bed': self.bed1.pk, 'attending_doctor': self.doctor.pk, 'diagnosis_summary': ''})
        self.assertTrue(form.is_valid())
        Bed.objects.filter(pk=self.bed1.pk).update(status=Bed.Status.OCCUPIED)  # someone else got there first
        with self.assertRaises(ValidationError):
            form.save(self.patient)
        self.assertFalse(Admission.objects.exists())


# --------------------------------------------------------------------------
# Appointments: the server must enforce the status flow, not just hide buttons.
# --------------------------------------------------------------------------
class AppointmentTransitionTests(TestCase):
    def setUp(self):
        make_user('desk', Role.FRONT_DESK)
        self.doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='desk', password='pw12345')
        self.patient = make_patient()

    def _appt(self, status):
        return Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=status)

    def _set(self, appt, status):
        self.client.post(reverse('appointments:set_status', args=[appt.pk, status]))
        appt.refresh_from_db()
        return appt.status

    def test_completed_cannot_be_reopened(self):
        self.assertEqual(self._set(self._appt('COMPLETED'), 'SCHEDULED'), 'COMPLETED')

    def test_cancelled_cannot_be_checked_in(self):
        self.assertEqual(self._set(self._appt('CANCELLED'), 'CHECKED_IN'), 'CANCELLED')

    def test_scheduled_cannot_jump_straight_to_completed(self):
        self.assertEqual(self._set(self._appt('SCHEDULED'), 'COMPLETED'), 'SCHEDULED')

    def test_legitimate_transitions_still_work(self):
        self.assertEqual(self._set(self._appt('SCHEDULED'), 'CHECKED_IN'), 'CHECKED_IN')
        self.assertEqual(self._set(self._appt('CHECKED_IN'), 'COMPLETED'), 'COMPLETED')
        self.assertEqual(self._set(self._appt('SCHEDULED'), 'CANCELLED'), 'CANCELLED')


# --------------------------------------------------------------------------
# Patient search must handle a full name, in either order.
# --------------------------------------------------------------------------
class PatientSearchTests(TestCase):
    def setUp(self):
        make_user('desk', Role.FRONT_DESK)
        self.client.login(username='desk', password='pw12345')
        self.chidinma = make_patient('Chidinma', 'Eze')
        self.tunde = make_patient('Tunde', 'Bakare')

    def _results(self, q):
        # Inspect the result set itself: the page echoes the query back into
        # the search box, so text matching would give false positives.
        response = self.client.get(reverse('patients:list'), {'q': q})
        return [p.pk for p in response.context['patients']]

    def test_full_name(self):
        self.assertEqual(self._results('Chidinma Eze'), [self.chidinma.pk])

    def test_reversed_name(self):
        self.assertEqual(self._results('eze chidinma'), [self.chidinma.pk])

    def test_partial_name_and_mrn(self):
        self.assertEqual(self._results('Chid'), [self.chidinma.pk])
        self.assertEqual(self._results(self.chidinma.mrn), [self.chidinma.pk])

    def test_no_match_returns_nothing(self):
        self.assertEqual(self._results('Chidinma Bakare'), [])


# --------------------------------------------------------------------------
# Vitals must be physiologically plausible, not just "a number".
# --------------------------------------------------------------------------
class VitalsValidationTests(TestCase):
    def setUp(self):
        make_user('doc', Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        self.patient = make_patient()
        self.url = reverse('ehr:patient_ehr', args=[self.patient.pk])

    def _post(self, **vitals):
        return self.client.post(self.url, {'add_encounter': '1', 'reason': 'Checkup', **vitals})

    def test_negative_pulse_rejected(self):
        self.assertEqual(self._post(pulse_bpm='-5').status_code, 200)
        self.assertFalse(Encounter.objects.exists())

    def test_spo2_over_100_rejected(self):
        self.assertEqual(self._post(spo2_percent='150').status_code, 200)
        self.assertFalse(Encounter.objects.exists())

    def test_absurd_temperature_rejected(self):
        self.assertEqual(self._post(temperature_c='90').status_code, 200)
        self.assertFalse(Encounter.objects.exists())

    def test_normal_vitals_accepted(self):
        self.assertEqual(self._post(pulse_bpm='80', spo2_percent='98', temperature_c='37.2').status_code, 302)


# --------------------------------------------------------------------------
# Billing: an invoice needs real, positive line items.
# --------------------------------------------------------------------------
class InvoiceValidationTests(TestCase):
    def setUp(self):
        make_user('bill', Role.BILLING)
        self.client.login(username='bill', password='pw12345')
        self.patient = make_patient()

    def _post(self, rows):
        data = {'patient': self.patient.pk, 'line_items-TOTAL_FORMS': str(len(rows)), 'line_items-INITIAL_FORMS': '0',
                'line_items-MIN_NUM_FORMS': '0', 'line_items-MAX_NUM_FORMS': '1000'}
        for i, (desc, amount) in enumerate(rows):
            data[f'line_items-{i}-description'] = desc
            data[f'line_items-{i}-amount'] = amount
        return self.client.post(reverse('billing:create'), data)

    def test_invoice_with_no_line_items_is_rejected(self):
        self.assertEqual(self._post([('', ''), ('', '')]).status_code, 200)
        self.assertFalse(Invoice.objects.exists())

    def test_negative_line_item_is_rejected(self):
        self.assertEqual(self._post([('Refund?', '-5000')]).status_code, 200)
        self.assertFalse(Invoice.objects.exists())

    def test_zero_line_item_is_rejected(self):
        self.assertEqual(self._post([('Freebie', '0')]).status_code, 200)
        self.assertFalse(Invoice.objects.exists())

    def test_valid_invoice_still_works(self):
        self.assertEqual(self._post([('Consultation', '5000'), ('', '')]).status_code, 302)


# --------------------------------------------------------------------------
# The seed command is a standing requirement: idempotent, covers every role,
# and never runs its destructive/known-password paths outside DEBUG.
# --------------------------------------------------------------------------
class SeedCommandTests(TestCase):
    def _seed(self, *args):
        call_command('seed_demo_data', *args, stdout=StringIO())

    def _snapshot(self):
        return {model.__name__: model.objects.count()
                for model in (User, Patient, Appointment, Invoice, Encounter, Admission, OPDVisit)}

    @override_settings(DEBUG=True)
    def test_idempotent(self):
        self._seed()
        first = self._snapshot()
        self._seed()
        self.assertEqual(first, self._snapshot())

    @override_settings(DEBUG=True)
    def test_every_role_gets_a_demo_login(self):
        self._seed()
        self.assertEqual(set(User.objects.values_list('role', flat=True)), set(Role.values))

    @override_settings(DEBUG=True)
    def test_beds_and_admissions_agree(self):
        """An occupied bed must have exactly one patient in it, and vice versa.
        (The demo once showed an occupied bed with nobody in it.)"""
        self._seed()
        occupied = set(Bed.objects.filter(status=Bed.Status.OCCUPIED).values_list('pk', flat=True))
        admitted = list(Admission.objects.filter(status=Admission.Status.ADMITTED).values_list('bed_id', flat=True))
        self.assertEqual(occupied, set(admitted))
        self.assertEqual(len(admitted), len(set(admitted)), "two active admissions share one bed")

    @override_settings(DEBUG=False)
    def test_refuses_to_run_when_debug_is_off(self):
        with self.assertRaises(CommandError):
            self._seed()
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=False)
    def test_force_overrides_the_debug_guard(self):
        self._seed('--force')
        self.assertTrue(User.objects.exists())


# --------------------------------------------------------------------------
# Smaller integrity fixes found in the same audit.
# --------------------------------------------------------------------------
class DashboardCountTests(TestCase):
    def test_appointments_today_kpi_is_not_capped_at_the_display_limit(self):
        doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        patient = make_patient()
        for _ in range(8):
            Appointment.objects.create(patient=patient, doctor=doctor, scheduled_for=timezone.now())
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['appointments_today_count'], 8)
        self.assertEqual(len(response.context['todays_appointments']), 6)  # the list itself stays short


class StatusRedirectTests(TestCase):
    def setUp(self):
        make_user('desk', Role.FRONT_DESK)
        self.doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='desk', password='pw12345')
        self.appt = Appointment.objects.create(patient=make_patient(), doctor=self.doctor, scheduled_for=timezone.now())
        self.url = reverse('appointments:set_status', args=[self.appt.pk, 'CHECKED_IN'])

    def test_foreign_referer_is_not_followed(self):
        response = self.client.post(self.url, HTTP_REFERER='https://evil.example/phish')
        self.assertRedirects(response, reverse('appointments:list'), fetch_redirect_response=False)

    def test_same_site_referer_is_followed(self):
        response = self.client.post(self.url, HTTP_REFERER='http://testserver/appointments/?scope=today')
        self.assertRedirects(response, 'http://testserver/appointments/?scope=today', fetch_redirect_response=False)


class ConsultDoesNotReviveAppointmentTests(TestCase):
    """A third audit pass found that a cancelled or already-completed
    appointment could still be consulted, creating a visit record that
    shouldn't exist -- the same bug class as the pharmacy/lab double-action
    fixes. The behavior this test checks for changed as a result: a
    cancelled appointment is now refused outright, not partially allowed."""

    def test_cancelled_appointment_is_refused_entirely(self):
        doctor = make_user('doc', Role.DOCTOR)
        self.client.login(username='doc', password='pw12345')
        patient = make_patient()
        appt = Appointment.objects.create(
            patient=patient, doctor=doctor, scheduled_for=timezone.now(), status=Appointment.Status.CANCELLED,
        )
        self.client.post(reverse('opd:consult_from_appointment', args=[patient.pk, appt.pk]), {'chief_complaint': 'Walk-in'})
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)
        self.assertFalse(OPDVisit.objects.filter(patient=patient).exists())  # no visit is created at all now


# ==========================================================================
# Second audit pass
# ==========================================================================
import os
import subprocess
import sys

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from accounts.permissions import LAB_ROLES, PHARMACY_ROLES, REVENUE_ROLES, has_role
from ehr.models import Vitals, Diagnosis, ClinicalNote
from ipd.models import CarePlan, MedicationAdministration
from opd.models import Prescription


# --------------------------------------------------------------------------
# Invoice.status is a stored field. It has to follow the payments and line
# items however they change, not only when our own view remembers to say so
# (the Django admin, scripts and the seed command all bypass the view).
# --------------------------------------------------------------------------
class InvoiceStatusStaysInSyncTests(TestCase):
    def setUp(self):
        self.invoice = Invoice.objects.create(patient=make_patient())
        LineItem.objects.create(invoice=self.invoice, description='Care', amount=10000)

    def _status(self):
        self.invoice.refresh_from_db()
        return self.invoice.status

    def test_partial_then_full_payment_outside_the_view(self):
        Payment.objects.create(invoice=self.invoice, amount=4000, method=Payment.Method.CASH)
        self.assertEqual(self._status(), Invoice.Status.PARTIAL)
        Payment.objects.create(invoice=self.invoice, amount=6000, method=Payment.Method.CASH)
        self.assertEqual(self._status(), Invoice.Status.PAID)

    def test_deleting_a_payment_reopens_the_invoice(self):
        payment = Payment.objects.create(invoice=self.invoice, amount=10000, method=Payment.Method.CASH)
        self.assertEqual(self._status(), Invoice.Status.PAID)
        payment.delete()
        self.assertEqual(self._status(), Invoice.Status.UNPAID)

    def test_adding_a_charge_to_a_paid_invoice_makes_it_partial(self):
        Payment.objects.create(invoice=self.invoice, amount=10000, method=Payment.Method.CASH)
        LineItem.objects.create(invoice=self.invoice, description='Extra night', amount=2000)
        self.assertEqual(self._status(), Invoice.Status.PARTIAL)

    def test_void_stays_void(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.VOID)
        Payment.objects.create(invoice=self.invoice, amount=10000, method=Payment.Method.CASH)
        self.assertEqual(self._status(), Invoice.Status.VOID)

    def test_deleting_a_whole_invoice_does_not_blow_up(self):
        Payment.objects.create(invoice=self.invoice, amount=1000, method=Payment.Method.CASH)
        self.invoice.delete()
        self.assertFalse(Invoice.objects.exists())


# --------------------------------------------------------------------------
# MRNs: two front-desk staff registering at once must not crash one of them,
# and the year in the MRN is the local (Lagos) year.
# --------------------------------------------------------------------------
class MRNRobustnessTests(TestCase):
    def test_collision_is_retried_instead_of_crashing(self):
        existing = make_patient('Ada', 'One')
        with mock.patch.object(Patient, '_generate_mrn', side_effect=[existing.mrn, 'WCH-2099-00042']):
            newcomer = make_patient('Bola', 'Two')
        self.assertEqual(newcomer.mrn, 'WCH-2099-00042')

    def test_a_non_mrn_integrity_error_is_not_swallowed(self):
        from django.db import IntegrityError
        with mock.patch('django.db.models.Model.save', side_effect=IntegrityError('boom')):
            with self.assertRaises(IntegrityError):
                Patient(first_name='X', last_name='Y', date_of_birth=datetime.date(1990, 1, 1), gender='F').save()

    def test_mrn_year_is_the_local_year(self):
        # 23:30 UTC on 31 Dec 2026 is already 1 Jan 2027 in Lagos
        new_year = datetime.datetime(2026, 12, 31, 23, 30, tzinfo=datetime.timezone.utc)
        with mock.patch('django.utils.timezone.now', return_value=new_year):
            patient = make_patient()
        self.assertTrue(patient.mrn.startswith('WCH-2027-'), patient.mrn)


# --------------------------------------------------------------------------
# Page cost must not grow with the number of rows (N+1 queries).
# --------------------------------------------------------------------------
class QueryCountTests(TestCase):
    def setUp(self):
        self.doctor = make_user('doc', Role.DOCTOR)
        self.client.force_login(self.doctor)

    def _queries(self, url):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(captured)

    def _assert_flat(self, url, add_rows):
        add_rows(2)
        few = self._queries(url)
        add_rows(10)
        many = self._queries(url)
        self.assertEqual(few, many, f"{url}: {few} queries with few rows, {many} with many")

    def test_invoice_list(self):
        self.client.force_login(make_user('bill', Role.BILLING))  # doctors are (correctly) locked out of billing
        patient = make_patient()

        def add(n):
            for _ in range(n):
                invoice = Invoice.objects.create(patient=patient)
                LineItem.objects.create(invoice=invoice, description='A', amount=1000)
                LineItem.objects.create(invoice=invoice, description='B', amount=500)
                Payment.objects.create(invoice=invoice, amount=500, method=Payment.Method.CASH)
        self._assert_flat(reverse('billing:list'), add)

    def test_bed_map(self):
        ward = Ward.objects.create(name='General')
        counter = iter(range(1000))

        def add(n):
            for _ in range(n):
                i = next(counter)
                bed = Bed.objects.create(ward=ward, bed_number=f'B-{i}', status=Bed.Status.OCCUPIED)
                Admission.objects.create(patient=make_patient(f'P{i}', 'X'), bed=bed, attending_doctor=self.doctor)
        self._assert_flat(reverse('ipd:bed_map'), add)

    def test_ehr_timeline(self):
        patient = make_patient()

        def add(n):
            for i in range(n):
                encounter = Encounter.objects.create(patient=patient, clinician=self.doctor, reason=f'Visit {i}')
                Vitals.objects.create(encounter=encounter, pulse_bpm=80)
                Diagnosis.objects.create(encounter=encounter, description='Malaria')
                ClinicalNote.objects.create(encounter=encounter, author=self.doctor, body='Note')
                visit = OPDVisit.objects.create(patient=patient, doctor=self.doctor, encounter=encounter, chief_complaint='Fever')
                Prescription.objects.create(opd_visit=visit, drug_name='ACT', dosage='80mg', frequency='2x', duration_days=3)
        self._assert_flat(reverse('ehr:patient_ehr', args=[patient.pk]), add)

    def test_admission_detail(self):
        ward = Ward.objects.create(name='General')
        bed = Bed.objects.create(ward=ward, bed_number='G-1', status=Bed.Status.OCCUPIED)
        admission = Admission.objects.create(patient=make_patient(), bed=bed, attending_doctor=self.doctor)

        def add(n):
            for _ in range(n):
                CarePlan.objects.create(admission=admission, instructions='Monitor', created_by=self.doctor)
                MedicationAdministration.objects.create(admission=admission, drug_name='Paracetamol', dose='1g', administered_by=self.doctor)
        self._assert_flat(reverse('ipd:detail', args=[admission.pk]), add)


# --------------------------------------------------------------------------
# The interface must only offer what the server will allow. Every role sees
# the same sidebar and buttons today, so most people can click something
# that ends in a bare "403 Forbidden".
# --------------------------------------------------------------------------
class UIMatchesServerPermissionsTests(TestCase):
    def setUp(self):
        self.patient = make_patient()
        self.doctor = make_user('seeddoc', Role.DOCTOR)
        ward = Ward.objects.create(name='General')
        Bed.objects.create(ward=ward, bed_number='G-01')  # available, so the admit page renders
        taken = Bed.objects.create(ward=ward, bed_number='G-02', status=Bed.Status.OCCUPIED)
        self.admission = Admission.objects.create(patient=make_patient('Other', 'Person'), bed=taken, attending_doctor=self.doctor)
        self.scheduled = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.SCHEDULED)
        self.waiting = Appointment.objects.create(patient=self.patient, doctor=self.doctor, scheduled_for=timezone.now(), status=Appointment.Status.CHECKED_IN)
        encounter = Encounter.objects.create(patient=self.patient, clinician=self.doctor, reason='Cough')
        visit = OPDVisit.objects.create(patient=self.patient, doctor=self.doctor, encounter=encounter, chief_complaint='Cough')
        self.prescription = Prescription.objects.create(opd_visit=visit, drug_name='Amoxicillin', dosage='250mg', frequency='3x daily', duration_days=7)

    def _cases(self):
        pk = self.patient.pk
        return [
            (reverse('core:dashboard'), [
                (f'href="{reverse("billing:list")}"', reverse('billing:list')),
                (f'href="{reverse("appointments:create")}"', reverse('appointments:create')),
                (f'href="{reverse("patients:register")}"', reverse('patients:register')),
                (f'href="{reverse("pharmacy:queue")}"', reverse('pharmacy:queue')),
                (f'href="{reverse("laboratory:queue")}"', reverse('laboratory:queue')),
            ]),
            (reverse('patients:list'), [
                (f'href="{reverse("patients:register")}"', reverse('patients:register')),
            ]),
            (reverse('patients:detail', args=[pk]), [
                (f'href="{reverse("ehr:patient_ehr", args=[pk])}"', reverse('ehr:patient_ehr', args=[pk])),
                (f'href="{reverse("opd:consult", args=[pk])}"', reverse('opd:consult', args=[pk])),
                (f'href="{reverse("ipd:admit", args=[pk])}"', reverse('ipd:admit', args=[pk])),
                (f'href="{reverse("billing:create")}?patient={pk}"', reverse('billing:create')),
                (f'href="{reverse("pharmacy:dispense", args=[pk])}"', reverse('pharmacy:dispense', args=[pk])),
                (f'href="{reverse("laboratory:order", args=[pk])}"', reverse('laboratory:order', args=[pk])),
            ]),

            (reverse('appointments:list') + '?scope=today', [
                (f'href="{reverse("appointments:create")}"', reverse('appointments:create')),
                (f'action="{reverse("appointments:set_status", args=[self.scheduled.pk, "CHECKED_IN"])}"',
                 reverse('appointments:set_status', args=[self.scheduled.pk, 'CHECKED_IN'])),
            ]),
            (reverse('opd:queue'), [
                (f'href="{reverse("opd:consult_from_appointment", args=[pk, self.waiting.pk])}"',
                 reverse('opd:consult_from_appointment', args=[pk, self.waiting.pk])),
            ]),
            (reverse('ipd:bed_map'), [
                (f'href="{reverse("ipd:detail", args=[self.admission.pk])}"', reverse('ipd:detail', args=[self.admission.pk])),
                (f'href="{reverse("ipd:manage")}"', reverse('ipd:manage')),
            ]),
        ]

    def _check(self, user):
        self.client.force_login(user)
        dashboard = self.client.get(reverse('core:dashboard')).content.decode()
        can_see_revenue = 'Revenue today' in dashboard
        allowed_revenue = has_role(user, REVENUE_ROLES)
        self.assertEqual(can_see_revenue, allowed_revenue,
                          f"{user.role}: revenue card shown={can_see_revenue}, but billing access={allowed_revenue}")

        can_see_low_stock = 'Low stock drugs' in dashboard
        allowed_pharmacy = has_role(user, PHARMACY_ROLES)
        self.assertEqual(can_see_low_stock, allowed_pharmacy,
                          f"{user.role}: low-stock card shown={can_see_low_stock}, but pharmacy access={allowed_pharmacy}")

        can_see_pending_lab = 'Pending lab results' in dashboard
        allowed_lab = has_role(user, LAB_ROLES)
        self.assertEqual(can_see_pending_lab, allowed_lab,
                          f"{user.role}: pending-lab card shown={can_see_pending_lab}, but lab access={allowed_lab}")

        for page, links in self._cases():
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200, f"{user.role} cannot even open {page}")
            html = response.content.decode()
            for needle, probe in links:
                shown = needle in html
                allowed = self.client.get(probe).status_code != 403
                with self.subTest(role=user.role, superuser=user.is_superuser, page=page, link=needle):
                    self.assertEqual(shown, allowed, "link is shown" if shown else "link is hidden but the server would allow it")
            self.client.force_login(user)

    def test_every_role(self):
        for role in Role.values:
            self._check(make_user(f'user_{role.lower()}', role))

    def test_superuser(self):
        self._check(make_user('root', Role.FRONT_DESK, is_superuser=True))

    def test_forbidden_page_is_friendly(self):
        self.client.force_login(make_user('nurse', Role.NURSE))
        response = self.client.get(reverse('billing:list'))
        self.assertContains(response, 'permission', status_code=403)
        self.assertContains(response, reverse('core:dashboard'), status_code=403)


# --------------------------------------------------------------------------
# Production settings: measured in a fresh interpreter, because settings are
# read once at import time.
# --------------------------------------------------------------------------
class ProductionSettingsTests(SimpleTestCase):
    def _read(self, **env):
        code = ("import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'\n"
                "from django.conf import settings as s\n"
                "print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS)")
        result = subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR, capture_output=True, text=True,
                                env={**os.environ, 'DB_ENGINE': 'sqlite', **env})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_production_is_hardened(self):
        session, csrf, redirect, hsts = self._read(DEBUG='False', SECRET_KEY='a-real-long-random-secret-value-0123456789-abcdef')
        self.assertEqual((session, csrf, redirect), ('True', 'True', 'True'))
        self.assertGreater(int(hsts), 0)

    def test_local_development_is_not_forced_onto_https(self):
        self.assertEqual(self._read(DEBUG='True'), ['False', 'False', 'False', '0'])


# --------------------------------------------------------------------------
# The admin section: reachable for those who can use it, hidden from everyone
# else, and branded.
# --------------------------------------------------------------------------
class AdminSectionAccessTests(TestCase):
    def test_only_superusers_are_pointed_at_the_admin(self):
        admin_link = f'href="{reverse("admin:index")}"'
        for role in Role.values:
            self.client.force_login(make_user(f'a_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertNotIn(admin_link, self.client.get(reverse('core:dashboard')).content.decode())

    def test_superuser_gets_a_link_that_leads_somewhere_useful(self):
        root = make_user('root', Role.FRONT_DESK, is_superuser=True, is_staff=True)
        self.client.force_login(root)
        self.assertIn(f'href="{reverse("admin:index")}"', self.client.get(reverse('core:dashboard')).content.decode())
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invoices')          # models are listed, i.e. it is actually usable
        self.assertContains(response, 'Willow Cross Hospital')  # branded with the hospital name

    def test_the_administrator_role_uses_the_app_screens_not_the_admin_site(self):
        self.client.force_login(make_user('adm', Role.ADMIN, is_staff=True))
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'permission to view or edit anything')


# --------------------------------------------------------------------------
# Three access decisions applied on request: patient registration is Front
# Desk/Admin only, dashboard revenue is billing-visible only, and everyone
# can change their own password.
# --------------------------------------------------------------------------
class PatientRegistrationAccessTests(TestCase):
    def setUp(self):
        self.url = reverse('patients:register')

    def test_front_desk_and_admin_can_register(self):
        for role in (Role.FRONT_DESK, Role.ADMIN):
            self.client.force_login(make_user(f'reg_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_clinical_and_billing_roles_cannot_register(self):
        for role in (Role.DOCTOR, Role.NURSE, Role.PHARMACIST, Role.LAB_TECH, Role.BILLING):
            self.client.force_login(make_user(f'reg2_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertFalse(Patient.objects.exists())

    def test_viewing_and_searching_patients_is_still_open_to_every_role(self):
        patient = make_patient()
        for role in Role.values:
            self.client.force_login(make_user(f'view_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertEqual(self.client.get(reverse('patients:list')).status_code, 200)
                self.assertEqual(self.client.get(reverse('patients:detail', args=[patient.pk])).status_code, 200)


class DashboardRevenueVisibilityTests(TestCase):
    def test_billing_and_admin_see_it_others_do_not(self):
        for role in Role.values:
            self.client.force_login(make_user(f'rev_{role.lower()}', role))
            response = self.client.get(reverse('core:dashboard'))
            shown = 'Revenue today' in response.content.decode()
            with self.subTest(role=role):
                self.assertEqual(shown, role in (Role.BILLING, Role.ADMIN))

    def test_the_figure_itself_is_still_computed_for_everyone(self):
        # Hidden in the template, not withheld from context -- a future
        # screen for a billing-visible role can reuse it without a new query.
        self.client.force_login(make_user('nurse2', Role.NURSE))
        response = self.client.get(reverse('core:dashboard'))
        self.assertIn('revenue_today', response.context)


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = make_user('pwuser', Role.NURSE)
        self.client.login(username='pwuser', password='pw12345')
        self.url = reverse('accounts:password_change')

    def test_every_role_has_a_link_to_it(self):
        for role in Role.values:
            self.client.force_login(make_user(f'link_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertContains(self.client.get(reverse('core:dashboard')), f'href="{self.url}"')

    def test_correct_current_password_changes_it(self):
        response = self.client.post(self.url, {
            'old_password': 'pw12345', 'new_password1': 'a-much-better-pw-2026', 'new_password2': 'a-much-better-pw-2026',
        })
        self.assertRedirects(response, reverse('accounts:password_change_done'))
        self.client.logout()
        self.assertTrue(self.client.login(username='pwuser', password='a-much-better-pw-2026'))
        self.assertFalse(self.client.login(username='pwuser', password='pw12345'))

    def test_wrong_current_password_is_rejected(self):
        response = self.client.post(self.url, {
            'old_password': 'wrong-password', 'new_password1': 'a-much-better-pw-2026', 'new_password2': 'a-much-better-pw-2026',
        })
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        self.assertTrue(self.client.login(username='pwuser', password='pw12345'))

    def test_mismatched_new_passwords_are_rejected(self):
        response = self.client.post(self.url, {
            'old_password': 'pw12345', 'new_password1': 'a-much-better-pw-2026', 'new_password2': 'does-not-match-2026',
        })
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        self.assertTrue(self.client.login(username='pwuser', password='pw12345'))

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
