import datetime
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse

from accounts.models import User, Role
from patients.models import Patient
from .models import Invoice, LineItem, Payment


class BillingAccessControlTests(TestCase):
    def setUp(self):
        self.billing_officer = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-9001', role=Role.BILLING)
        self.doctor = User.objects.create_user(username='doc', password='pw12345', staff_id='WCH-9002', role=Role.DOCTOR)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')

    def test_billing_officer_can_view_list(self):
        self.client.login(username='bill', password='pw12345')
        response = self.client.get(reverse('billing:list'))
        self.assertEqual(response.status_code, 200)

    def test_doctor_forbidden_from_billing_list(self):
        self.client.login(username='doc', password='pw12345')
        response = self.client.get(reverse('billing:list'))
        self.assertEqual(response.status_code, 403)

    def test_doctor_forbidden_from_creating_invoice(self):
        self.client.login(username='doc', password='pw12345')
        response = self.client.get(reverse('billing:create'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected(self):
        response = self.client.get(reverse('billing:list'))
        self.assertEqual(response.status_code, 302)


class InvoiceCreationTests(TestCase):
    def setUp(self):
        self.billing_officer = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-9001', role=Role.BILLING)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.client.login(username='bill', password='pw12345')

    def _formset_data(self, rows):
        data = {'line_items-TOTAL_FORMS': str(len(rows)), 'line_items-INITIAL_FORMS': '0',
                'line_items-MIN_NUM_FORMS': '0', 'line_items-MAX_NUM_FORMS': '1000'}
        for i, (desc, amount) in enumerate(rows):
            data[f'line_items-{i}-description'] = desc
            data[f'line_items-{i}-amount'] = amount
        return data

    def test_creating_invoice_with_line_items(self):
        data = {'patient': self.patient.pk, **self._formset_data([('Consultation', '15000'), ('Lab test', '8500')])}
        response = self.client.post(reverse('billing:create'), data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(patient=self.patient)
        self.assertEqual(invoice.total, Decimal('23500'))
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)

    def test_blank_line_item_rows_are_skipped(self):
        data = {'patient': self.patient.pk, **self._formset_data([('Consultation', '15000'), ('', '')])}
        response = self.client.post(reverse('billing:create'), data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(patient=self.patient)
        self.assertEqual(invoice.line_items.count(), 1)

    def test_more_than_three_lines_were_always_accepted_by_the_backend(self):
        # The old template only ever rendered 3 rows, but the formset itself
        # (extra=3) only limits the initial GET render, not what POST accepts.
        rows = [(f'Item {i}', str(1000 + i)) for i in range(6)]
        data = {'patient': self.patient.pk, **self._formset_data(rows)}
        response = self.client.post(reverse('billing:create'), data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(patient=self.patient)
        self.assertEqual(invoice.line_items.count(), 6)

    def test_get_request_includes_the_add_line_control_and_empty_form_template(self):
        response = self.client.get(reverse('billing:create'))
        self.assertContains(response, 'id="add-line"')
        self.assertContains(response, 'id="line-item-empty-form"')
        self.assertContains(response, '__prefix__')

    def test_no_patient_selected_does_not_create_invoice(self):
        data = self._formset_data([('Consultation', '15000')])
        response = self.client.post(reverse('billing:create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())


class PaymentTests(TestCase):
    def setUp(self):
        self.billing_officer = User.objects.create_user(username='bill', password='pw12345', staff_id='WCH-9001', role=Role.BILLING)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.invoice = Invoice.objects.create(patient=self.patient)
        LineItem.objects.create(invoice=self.invoice, description='Consultation', amount=Decimal('10000'))
        self.client.login(username='bill', password='pw12345')

    def test_partial_payment_sets_partial_status(self):
        self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {
            'add_payment': '1', 'amount': '4000', 'method': 'CASH',
        })
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(self.invoice.balance, Decimal('6000'))

    def test_full_payment_sets_paid_status(self):
        self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {
            'add_payment': '1', 'amount': '10000', 'method': 'TRANSFER',
        })
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertEqual(self.invoice.balance, Decimal('0'))

    def test_overpayment_is_rejected(self):
        response = self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {
            'add_payment': '1', 'amount': '15000', 'method': 'CASH',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'outstanding balance')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.UNPAID)

    def test_zero_or_negative_payment_is_rejected(self):
        response = self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {
            'add_payment': '1', 'amount': '0', 'method': 'CASH',
        })
        self.assertContains(response, 'greater than zero')
        self.assertFalse(Payment.objects.exists())

    def test_two_partial_payments_accumulate_to_paid(self):
        self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {'add_payment': '1', 'amount': '6000', 'method': 'CASH'})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.client.post(reverse('billing:detail', args=[self.invoice.pk]), {'add_payment': '1', 'amount': '4000', 'method': 'CASH'})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)


# ==========================================================================
# Add a charge to an existing invoice, and print an invoice
# ==========================================================================
from django.core.exceptions import ValidationError
from django.test import override_settings


def _invoice_with_charge(patient, amount='10000'):
    invoice = Invoice.objects.create(patient=patient)
    LineItem.objects.create(invoice=invoice, description='Bed charge', amount=Decimal(amount))
    return invoice


class AddChargeToExistingInvoiceTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='bill2', password='pw12345', staff_id='WCH-9101', role=Role.BILLING)
        User.objects.create_user(username='doc2', password='pw12345', staff_id='WCH-9102', role=Role.DOCTOR)
        self.patient = Patient.objects.create(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M')
        self.invoice = _invoice_with_charge(self.patient)
        self.url = reverse('billing:detail', args=[self.invoice.pk])
        self.client.login(username='bill2', password='pw12345')

    def _add(self, description='Extra night', amount='2000'):
        return self.client.post(self.url, {'add_line': '1', 'description': description, 'amount': amount})

    def _status(self):
        self.invoice.refresh_from_db()
        return self.invoice.status

    def test_page_offers_the_form_and_a_print_link(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Add a charge')
        self.assertContains(response, reverse('billing:print', args=[self.invoice.pk]))

    def test_adds_a_line_and_the_total_follows(self):
        response = self._add()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.invoice.line_items.count(), 2)
        self.assertEqual(self.invoice.total, Decimal('12000'))

    def test_a_charge_on_a_paid_invoice_reopens_it(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal('10000'), method=Payment.Method.CASH)
        self.assertEqual(self._status(), Invoice.Status.PAID)
        self._add()
        self.assertEqual(self._status(), Invoice.Status.PARTIAL)
        self.assertEqual(self.invoice.balance, Decimal('2000'))

    def test_rejects_zero_negative_and_blank(self):
        for description, amount in [('Free?', '0'), ('Refund?', '-500'), ('', '1000'), ('No amount', '')]:
            with self.subTest(description=description, amount=amount):
                self.assertEqual(self._add(description, amount).status_code, 200)
        self.assertEqual(self.invoice.line_items.count(), 1)

    def test_a_void_invoice_is_closed(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.VOID)
        self._add()
        self.client.post(self.url, {'add_payment': '1', 'amount': '1000', 'method': 'CASH'})
        self.assertEqual(self.invoice.line_items.count(), 1)
        self.assertFalse(Payment.objects.exists())

    def test_only_billing_roles_may_add_charges(self):
        self.client.login(username='doc2', password='pw12345')
        self.assertEqual(self._add().status_code, 403)
        self.assertEqual(self.invoice.line_items.count(), 1)


class LineItemModelValidationTests(TestCase):
    """The admin builds its forms from the model, so the rule has to live there."""

    def test_non_positive_amounts_fail_full_clean(self):
        patient = Patient.objects.create(first_name='A', last_name='B', date_of_birth=datetime.date(1990, 1, 1), gender='F')
        invoice = Invoice.objects.create(patient=patient)
        for bad in ('-5', '0'):
            with self.assertRaises(ValidationError):
                LineItem(invoice=invoice, description='x', amount=Decimal(bad)).full_clean()
        LineItem(invoice=invoice, description='x', amount=Decimal('0.01')).full_clean()


class PrintInvoiceTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='bill3', password='pw12345', staff_id='WCH-9103', role=Role.BILLING)
        User.objects.create_user(username='doc3', password='pw12345', staff_id='WCH-9104', role=Role.DOCTOR)
        self.patient = Patient.objects.create(
            first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F',
            phone_number='08012345678', address='14 Market Road\nOnitsha',
        )
        self.invoice = Invoice.objects.create(patient=self.patient)
        LineItem.objects.create(invoice=self.invoice, description='Antenatal consultation', amount=Decimal('15000'))
        LineItem.objects.create(invoice=self.invoice, description='Lab panel', amount=Decimal('8500'))
        Payment.objects.create(invoice=self.invoice, amount=Decimal('5000'), method=Payment.Method.TRANSFER)
        self.url = reverse('billing:print', args=[self.invoice.pk])
        self.client.login(username='bill3', password='pw12345')

    def test_shows_everything_a_customer_needs(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for expected in ['Chidinma Eze', self.patient.mrn, '08012345678', 'Onitsha', 'Antenatal consultation', 'Lab panel',
                         '23,500.00', '5,000.00', '18,500.00', 'Bank transfer', 'PARTIAL', f'No. {self.invoice.pk}']:
            self.assertContains(response, expected)

    def test_is_a_clean_page_with_a_print_button(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('window.print()', html)
        self.assertNotIn('class="sidebar"', html)
        self.assertNotIn('class="topbar"', html)

    def test_hospital_details_come_from_settings(self):
        self.assertContains(self.client.get(self.url), 'Willow Cross Hospital')
        with override_settings(HOSPITAL_NAME='Acme Clinic', HOSPITAL_ADDRESS='1 Test Road', HOSPITAL_PHONE='0800-000'):
            response = self.client.get(self.url)
        for expected in ('Acme Clinic', '1 Test Road', '0800-000'):
            self.assertContains(response, expected)

    def test_a_void_invoice_is_marked_void(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.VOID)
        self.assertContains(self.client.get(self.url), 'VOID')

    def test_only_billing_roles_can_print(self):
        self.client.login(username='doc3', password='pw12345')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
