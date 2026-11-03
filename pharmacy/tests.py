import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Role
from ehr.models import Allergy
from ehr.models import Encounter
from opd.models import OPDVisit, Prescription
from patients.models import Patient
from .models import Batch, Drug, DispenseRecord


def make_user(username, role):
    return User.objects.create_user(username=username, password='pw12345', staff_id=f'T-{username}', role=role)


def make_patient(first='Chidinma', last='Eze'):
    return Patient.objects.create(first_name=first, last_name=last, date_of_birth=datetime.date(1990, 4, 12), gender='F')


def make_drug(name='Amoxicillin', strength='250mg', **extra):
    return Drug.objects.create(name=name, strength=strength, unit_price=Decimal('350'), **extra)


class PharmacyAccessControlTests(TestCase):
    def setUp(self):
        self.patient = make_patient()
        self.pharmacist = make_user('pharm', Role.PHARMACIST)
        self.nurse = make_user('nurse', Role.NURSE)

    def test_pharmacist_can_reach_every_screen(self):
        self.client.login(username='pharm', password='pw12345')
        for url in (reverse('pharmacy:queue'), reverse('pharmacy:inventory'), reverse('pharmacy:dispense', args=[self.patient.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_every_other_role_is_refused(self):
        for role in (Role.DOCTOR, Role.NURSE, Role.FRONT_DESK, Role.BILLING, Role.LAB_TECH):
            self.client.login(username=f'u_{role}', password='pw12345') if User.objects.filter(username=f'u_{role}').exists() else make_user(f'u_{role}', role)
            self.client.login(username=f'u_{role}', password='pw12345')
            for url in (reverse('pharmacy:queue'), reverse('pharmacy:inventory'), reverse('pharmacy:dispense', args=[self.patient.pk])):
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(reverse('pharmacy:queue')).status_code, 302)


class DispenseStockTests(TestCase):
    def setUp(self):
        self.pharmacist = make_user('pharm2', Role.PHARMACIST)
        self.client.login(username='pharm2', password='pw12345')
        self.patient = make_patient()
        self.drug = make_drug()

    def _dispense(self, quantity, **extra):
        return self.client.post(reverse('pharmacy:dispense', args=[self.patient.pk]), {
            'drug': self.drug.pk, 'quantity': quantity, **extra,
        })

    def test_dispensing_deducts_from_the_oldest_expiring_batch_first(self):
        today = timezone.localdate()
        soon = Batch.objects.create(drug=self.drug, batch_number='A', quantity=10, expiry_date=today + datetime.timedelta(days=10))
        later = Batch.objects.create(drug=self.drug, batch_number='B', quantity=10, expiry_date=today + datetime.timedelta(days=100))
        self._dispense(15)
        soon.refresh_from_db(); later.refresh_from_db()
        self.assertEqual(soon.quantity, 0)      # fully used first (FEFO)
        self.assertEqual(later.quantity, 5)     # only the remainder taken from this one

    def test_expired_batches_are_never_touched(self):
        today = timezone.localdate()
        expired = Batch.objects.create(drug=self.drug, batch_number='X', quantity=100, expiry_date=today - datetime.timedelta(days=1))
        good = Batch.objects.create(drug=self.drug, batch_number='Y', quantity=10, expiry_date=today + datetime.timedelta(days=100))
        response = self._dispense(15)  # more than the 10 unexpired units
        self.assertEqual(response.status_code, 200)  # rejected: only 10 available
        expired.refresh_from_db(); good.refresh_from_db()
        self.assertEqual(expired.quantity, 100)
        self.assertEqual(good.quantity, 10)
        self.assertFalse(DispenseRecord.objects.exists())

    def test_save_itself_skips_expired_batches_not_just_the_upfront_total_check(self):
        """Distinct from test_expired_batches_are_never_touched: that one is
        rejected by clean()'s total_stock check before save() ever runs a
        query. Here the requested quantity exactly matches the unexpired
        stock, so clean() passes and save()'s own batch-selection query is
        what has to get this right. If it wrongly included the expired batch
        -- which sorts first, being the earliest expiry date -- it would draw
        from expired stock instead of the valid batch."""
        today = timezone.localdate()
        expired = Batch.objects.create(drug=self.drug, batch_number='X', quantity=100, expiry_date=today - datetime.timedelta(days=1))
        good = Batch.objects.create(drug=self.drug, batch_number='Y', quantity=10, expiry_date=today + datetime.timedelta(days=100))
        response = self._dispense(10)
        self.assertEqual(response.status_code, 302)
        expired.refresh_from_db(); good.refresh_from_db()
        self.assertEqual(expired.quantity, 100, "the expired batch must not be touched")
        self.assertEqual(good.quantity, 0, "the valid batch should have been used")

    def test_cannot_dispense_more_than_total_stock(self):
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=5, expiry_date=timezone.localdate() + datetime.timedelta(days=30))
        response = self._dispense(6)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'in stock')
        self.assertFalse(DispenseRecord.objects.exists())

    def test_successful_dispense_creates_a_record_and_redirects_to_patient_profile(self):
        # Not the EHR: a pharmacist doesn't have EHR access, and shouldn't
        # need it just to confirm what they dispensed.
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=20, expiry_date=timezone.localdate() + datetime.timedelta(days=30))
        response = self._dispense(5)
        self.assertRedirects(response, reverse('patients:detail', args=[self.patient.pk]))
        record = DispenseRecord.objects.get()
        self.assertEqual(record.quantity, 5)
        self.assertEqual(record.dispensed_by, self.pharmacist)
        self.assertIsNone(record.prescription)

    def test_concurrent_dispense_cannot_oversell_stock(self):
        """Two pharmacists both pass validation against the same 10 units, then
        both try to save. The second must fail cleanly, not create negative stock."""
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=10, expiry_date=timezone.localdate() + datetime.timedelta(days=30))
        from .forms import DispenseForm
        form1 = DispenseForm(data={'drug': self.drug.pk, 'quantity': 10}, patient=self.patient)
        form2 = DispenseForm(data={'drug': self.drug.pk, 'quantity': 10}, patient=self.patient)
        self.assertTrue(form1.is_valid())
        self.assertTrue(form2.is_valid())  # both see 10 available; neither has saved yet
        form1.save(self.patient, self.pharmacist)
        with self.assertRaises(Exception):
            form2.save(self.patient, self.pharmacist)
        self.assertEqual(Batch.objects.get(pk__in=[self.drug.batches.first().pk]).quantity, 0)
        self.assertEqual(DispenseRecord.objects.count(), 1)


class AllergyGateTests(TestCase):
    def setUp(self):
        make_user('pharm3', Role.PHARMACIST)
        self.client.login(username='pharm3', password='pw12345')
        self.patient = make_patient()
        self.drug = make_drug(name='Penicillin')
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=50, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        Allergy.objects.create(patient=self.patient, substance='Penicillin', severity='SEVERE')

    def _dispense(self, **extra):
        return self.client.post(reverse('pharmacy:dispense', args=[self.patient.pk]), {
            'drug': self.drug.pk, 'quantity': 1, **extra,
        })

    def test_blocked_without_acknowledgement(self):
        response = self._dispense()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'recorded allergy')
        self.assertFalse(DispenseRecord.objects.exists())

    def test_allowed_once_acknowledged(self):
        response = self._dispense(acknowledge_allergy='on')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DispenseRecord.objects.exists())

    def test_acknowledgement_checkbox_only_shown_when_patient_has_an_allergy_on_file(self):
        patient_without = make_patient('Musa', 'Abdullahi')
        response = self.client.get(reverse('pharmacy:dispense', args=[patient_without.pk]))
        self.assertNotContains(response, 'reviewed this allergy')

    def test_acknowledgement_checkbox_shown_whenever_patient_has_any_allergy_on_file(self):
        # Shown for any drug once the patient has an allergy recorded, since
        # the form is plain server-rendered HTML with no live drug-vs-allergy
        # check as the dropdown changes.
        other = make_drug(name='Paracetamol')
        Batch.objects.create(drug=other, batch_number='B', quantity=50, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        response = self.client.get(reverse('pharmacy:dispense', args=[self.patient.pk]))
        self.assertContains(response, 'reviewed this allergy')

    def test_unrelated_drug_is_not_blocked(self):
        other = make_drug(name='Paracetamol')
        Batch.objects.create(drug=other, batch_number='B', quantity=50, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        response = self.client.post(reverse('pharmacy:dispense', args=[self.patient.pk]), {'drug': other.pk, 'quantity': 1})
        self.assertEqual(response.status_code, 302)


class DispenseFromPrescriptionTests(TestCase):
    def setUp(self):
        self.pharmacist = make_user('pharm4', Role.PHARMACIST)
        self.doctor = make_user('doc4', Role.DOCTOR)
        self.client.login(username='pharm4', password='pw12345')
        self.patient = make_patient()
        encounter = Encounter.objects.create(patient=self.patient, clinician=self.doctor, reason='Cough')
        visit = OPDVisit.objects.create(patient=self.patient, doctor=self.doctor, encounter=encounter, chief_complaint='Cough')
        self.prescription = Prescription.objects.create(opd_visit=visit, drug_name='Amoxicillin', dosage='250mg', frequency='3x daily', duration_days=7)
        self.drug = make_drug(name='Amoxicillin')
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=50, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        self.url = reverse('pharmacy:dispense_from_prescription', args=[self.patient.pk, self.prescription.pk])

    def test_drug_is_preselected_from_the_prescription_text(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['form'].initial.get('drug'), self.drug.pk)

    def test_dispensing_links_back_to_the_prescription(self):
        self.client.post(self.url, {'drug': self.drug.pk, 'quantity': 21})
        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.dispense_record.quantity, 21)

    def test_prescription_for_a_different_patient_is_rejected(self):
        other = make_patient('Musa', 'Abdullahi')
        url = reverse('pharmacy:dispense_from_prescription', args=[other.pk, self.prescription.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_already_dispensed_prescription_redirects_from_the_queue(self):
        self.client.post(self.url, {'drug': self.drug.pk, 'quantity': 21})
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('pharmacy:queue'))

    def test_queue_lists_pending_and_drops_dispensed(self):
        response = self.client.get(reverse('pharmacy:queue'))
        self.assertContains(response, self.patient.full_name)
        self.client.post(self.url, {'drug': self.drug.pk, 'quantity': 21})
        response = self.client.get(reverse('pharmacy:queue'))
        self.assertContains(response, 'No pending prescriptions')

    def test_dispensed_status_shows_in_the_ehr_timeline(self):
        # The pharmacist dispenses; a doctor (who actually has EHR access)
        # confirms the status flipped from Pending to Dispensed.
        ehr_url = reverse('ehr:patient_ehr', args=[self.patient.pk])
        self.client.post(self.url, {'drug': self.drug.pk, 'quantity': 21})
        self.client.login(username='doc4', password='pw12345')
        self.assertContains(self.client.get(ehr_url), 'Dispensed')

    def test_pending_prescription_shows_as_pending_in_the_ehr_timeline(self):
        self.client.login(username='doc4', password='pw12345')
        self.assertContains(self.client.get(reverse('ehr:patient_ehr', args=[self.patient.pk])), 'Pending')


class InventoryTests(TestCase):
    def setUp(self):
        make_user('pharm5', Role.PHARMACIST)
        self.client.login(username='pharm5', password='pw12345')

    def test_add_drug(self):
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_drug': '1', 'name': 'Ibuprofen', 'strength': '400mg', 'unit_price': '150', 'reorder_level': '30',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Drug.objects.filter(name='Ibuprofen').exists())

    def test_add_drug_rejects_non_positive_price(self):
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_drug': '1', 'name': 'Ibuprofen', 'strength': '400mg', 'unit_price': '0', 'reorder_level': '30',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Drug.objects.filter(name='Ibuprofen').exists())

    def test_receive_stock(self):
        drug = make_drug()
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_batch': '1', 'drug': drug.pk, 'batch_number': 'B-1', 'quantity': '100',
            'expiry_date': (timezone.localdate() + datetime.timedelta(days=180)).isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(drug.total_stock, 100)

    def test_receive_stock_rejects_a_past_expiry_date(self):
        drug = make_drug()
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_batch': '1', 'drug': drug.pk, 'batch_number': 'B-1', 'quantity': '100',
            'expiry_date': (timezone.localdate() - datetime.timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'in the past')
        self.assertEqual(drug.total_stock, 0)

    def test_low_stock_and_expiring_soon_badges(self):
        drug = make_drug(reorder_level=50)
        Batch.objects.create(drug=drug, batch_number='A', quantity=10, expiry_date=timezone.localdate() + datetime.timedelta(days=10))
        response = self.client.get(reverse('pharmacy:inventory'))
        self.assertContains(response, 'Low stock')
        self.assertContains(response, 'Expiring soon')

    def test_expired_batch_does_not_count_as_stock(self):
        drug = make_drug()
        Batch.objects.create(drug=drug, batch_number='A', quantity=999, expiry_date=timezone.localdate() - datetime.timedelta(days=1))
        self.assertEqual(drug.total_stock, 0)


class DashboardLowStockTests(TestCase):
    def test_low_stock_count_reflects_unexpired_stock_only(self):
        make_user('pharm6', Role.PHARMACIST)
        self.client.login(username='pharm6', password='pw12345')
        low = make_drug(name='Metformin', reorder_level=50)
        Batch.objects.create(drug=low, batch_number='A', quantity=5, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        healthy = make_drug(name='Amoxicillin', reorder_level=10)
        Batch.objects.create(drug=healthy, batch_number='B', quantity=200, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['low_stock_count'], 1)

    def test_card_hidden_from_non_pharmacy_roles(self):
        make_user('doc5', Role.DOCTOR)
        self.client.login(username='doc5', password='pw12345')
        response = self.client.get(reverse('core:dashboard'))
        self.assertNotContains(response, 'Low stock drugs')


# ==========================================================================
# Second audit pass
# ==========================================================================
from django.db import transaction as db_transaction


class DrugDeletionTests(TestCase):
    """Deleting a drug from the catalog must never destroy dispensing history
    -- that's an audit trail, the same as an invoice or a lab result."""

    def test_deleting_a_drug_with_dispense_history_is_blocked(self):
        drug = make_drug()
        patient = make_patient()
        DispenseRecord.objects.create(drug=drug, patient=patient, quantity=5, dispensed_by=make_user('pharmX', Role.PHARMACIST))
        with self.assertRaises(Exception):
            with db_transaction.atomic():
                drug.delete()
        self.assertTrue(DispenseRecord.objects.filter(drug=drug).exists())

    def test_a_drug_with_no_history_can_still_be_deleted(self):
        drug = make_drug()
        drug.delete()
        self.assertFalse(Drug.objects.filter(pk=drug.pk).exists())


class GuessDrugEdgeCaseTests(TestCase):
    """_guess_drug reads prescription.drug_name.split()[0] -- a whitespace-only
    name would make split() return [] and raise IndexError on [0]."""

    def setUp(self):
        self.pharmacist = make_user('pharm7', Role.PHARMACIST)
        self.client.login(username='pharm7', password='pw12345')
        self.doctor = make_user('doc7', Role.DOCTOR)
        self.patient = make_patient()
        encounter = Encounter.objects.create(patient=self.patient, clinician=self.doctor, reason='Cough')
        visit = OPDVisit.objects.create(patient=self.patient, doctor=self.doctor, encounter=encounter, chief_complaint='Cough')
        # A prescription with only whitespace for the drug name shouldn't be
        # reachable through the app's own forms, but the admin or a script
        # could still create one -- the dispense page must not crash on it.
        self.prescription = Prescription.objects.create(opd_visit=visit, drug_name='   ', dosage='1', frequency='1', duration_days=1)

    def test_whitespace_only_prescription_name_does_not_crash_the_dispense_page(self):
        url = reverse('pharmacy:dispense_from_prescription', args=[self.patient.pk, self.prescription.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class ConcurrentDispenseFromPrescriptionTests(TestCase):
    """Two pharmacists open the same pending prescription at once. Both pass
    the "not yet dispensed" check before either saves. The second save must
    fail as a clean, handled error -- not an unhandled IntegrityError (500)
    from the OneToOneField's unique constraint."""

    def setUp(self):
        self.pharmacist = make_user('pharm8', Role.PHARMACIST)
        self.doctor = make_user('doc8', Role.DOCTOR)
        self.patient = make_patient()
        encounter = Encounter.objects.create(patient=self.patient, clinician=self.doctor, reason='Cough')
        visit = OPDVisit.objects.create(patient=self.patient, doctor=self.doctor, encounter=encounter, chief_complaint='Cough')
        self.prescription = Prescription.objects.create(opd_visit=visit, drug_name='Amoxicillin', dosage='250mg', frequency='3x daily', duration_days=7)
        self.drug = make_drug(name='Amoxicillin')
        Batch.objects.create(drug=self.drug, batch_number='A', quantity=100, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        self.client.login(username='pharm8', password='pw12345')

    def test_second_concurrent_dispense_is_a_clean_error_not_a_500(self):
        from django.core.exceptions import ValidationError
        from .forms import DispenseForm
        form1 = DispenseForm(data={'drug': self.drug.pk, 'quantity': 10}, patient=self.patient)
        form2 = DispenseForm(data={'drug': self.drug.pk, 'quantity': 10}, patient=self.patient)
        self.assertTrue(form1.is_valid())
        self.assertTrue(form2.is_valid())
        form1.save(self.patient, self.pharmacist, self.prescription)
        # The second save re-checks the prescription under a lock and raises a
        # normal, catchable ValidationError -- not the OneToOneField's raw
        # IntegrityError, which the view would have had no way to handle.
        with self.assertRaises(ValidationError):
            form2.save(self.patient, self.pharmacist, self.prescription)
        self.assertEqual(DispenseRecord.objects.filter(prescription=self.prescription).count(), 1)

    def test_the_view_itself_handles_this_gracefully(self):
        url = reverse('pharmacy:dispense_from_prescription', args=[self.patient.pk, self.prescription.pk])
        # Simulate: prescription was unfulfilled when the page loaded, but
        # another pharmacist dispenses it a moment before this POST arrives.
        DispenseRecord.objects.create(drug=self.drug, patient=self.patient, quantity=5,
                                       dispensed_by=self.pharmacist, prescription=self.prescription)
        response = self.client.post(url, {'drug': self.drug.pk, 'quantity': 10})
        self.assertNotEqual(response.status_code, 500)


class CatalogDuplicateTests(TestCase):
    def setUp(self):
        self.pharmacist = make_user('pharm9', Role.PHARMACIST)
        self.client.login(username='pharm9', password='pw12345')

    def test_adding_the_same_drug_twice_is_rejected(self):
        make_drug(name='Amoxicillin')
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_drug': '1', 'name': 'Amoxicillin', 'strength': '250mg', 'unit_price': '350', 'reorder_level': '50',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Drug.objects.filter(name='Amoxicillin').count(), 1)
        # The rejection is a non-field error (from the UniqueConstraint, not
        # any one field), so it needs its own place in the template -- it's
        # easy to silently drop, leaving the pharmacist with no idea why
        # nothing happened.
        self.assertContains(response, 'already exists')

    def test_different_strength_is_a_different_drug(self):
        make_drug(name='Amoxicillin', strength='250mg')
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_drug': '1', 'name': 'Amoxicillin', 'strength': '500mg', 'unit_price': '350', 'reorder_level': '50',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Drug.objects.filter(name='Amoxicillin').count(), 2)

    def test_duplicate_batch_number_for_the_same_drug_is_rejected(self):
        drug = make_drug()
        Batch.objects.create(drug=drug, batch_number='LOT-1', quantity=10, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_batch': '1', 'drug': drug.pk, 'batch_number': 'LOT-1', 'quantity': '50',
            'expiry_date': (timezone.localdate() + datetime.timedelta(days=200)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Batch.objects.filter(drug=drug, batch_number='LOT-1').count(), 1)

    def test_same_batch_number_is_fine_for_a_different_drug(self):
        drug1, drug2 = make_drug(name='Amoxicillin'), make_drug(name='Paracetamol')
        Batch.objects.create(drug=drug1, batch_number='LOT-1', quantity=10, expiry_date=timezone.localdate() + datetime.timedelta(days=100))
        response = self.client.post(reverse('pharmacy:inventory'), {
            'add_batch': '1', 'drug': drug2.pk, 'batch_number': 'LOT-1', 'quantity': '50',
            'expiry_date': (timezone.localdate() + datetime.timedelta(days=200)).isoformat(),
        })
        self.assertEqual(response.status_code, 302)
