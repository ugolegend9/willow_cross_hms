from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from accounts.permissions import BILLING_ROLES
from .forms import InvoicePatientForm, LineItemForm, LineItemFormSet, PaymentForm
from .models import Invoice


@login_required
@role_required(*BILLING_ROLES)
def invoice_list(request):
    status = request.GET.get('status', 'all')
    qs = Invoice.objects.select_related('patient').prefetch_related('line_items', 'payments').order_by('-created_at')
    if status != 'all':
        qs = qs.filter(status=status.upper())
    return render(request, 'billing/invoice_list.html', {
        'invoices': qs[:200], 'status': status, 'active_nav': 'billing',
    })


@login_required
@role_required(*BILLING_ROLES)
def invoice_create(request):
    initial_patient = request.GET.get('patient')

    if request.method == 'POST':
        patient_form = InvoicePatientForm(request.POST)
        invoice = Invoice()
        if patient_form.is_valid():
            invoice.patient = patient_form.cleaned_data['patient']
        formset = LineItemFormSet(request.POST, instance=invoice)
        if patient_form.is_valid() and formset.is_valid():
            invoice.save()
            formset.instance = invoice
            formset.save()
            messages.success(request, f"Invoice #{invoice.pk} created for {invoice.patient.full_name}.")
            return redirect('billing:detail', pk=invoice.pk)
    else:
        patient_form = InvoicePatientForm(initial={'patient': initial_patient} if initial_patient else None)
        formset = LineItemFormSet(instance=Invoice())

    return render(request, 'billing/invoice_form.html', {
        'patient_form': patient_form, 'formset': formset, 'empty_form': formset.empty_form, 'active_nav': 'billing',
    })


@login_required
@role_required(*BILLING_ROLES)
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    payment_form = PaymentForm(invoice=invoice)
    line_form = LineItemForm()

    if request.method == 'POST':
        # A void invoice is closed: no new charges and no new payments.
        if invoice.status == Invoice.Status.VOID and ('add_payment' in request.POST or 'add_line' in request.POST):
            messages.error(request, "This invoice is void, so it can't be changed.")
            return redirect('billing:detail', pk=pk)

        if 'add_payment' in request.POST:
            payment_form = PaymentForm(request.POST, invoice=invoice)
            if payment_form.is_valid():
                payment = payment_form.save(commit=False)
                payment.invoice = invoice
                payment.save()  # the invoice status follows automatically (billing/signals.py)
                messages.success(request, f"Payment of ₦{payment.amount:,.2f} recorded.")
                return redirect('billing:detail', pk=pk)

        elif 'add_line' in request.POST:
            line_form = LineItemForm(request.POST)
            if line_form.is_valid():
                item = line_form.save(commit=False)
                item.invoice = invoice
                item.save()
                messages.success(request, f"Added “{item.description}” (₦{item.amount:,.2f}) to invoice #{invoice.pk}.")
                return redirect('billing:detail', pk=pk)

    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice,
        'payment_form': payment_form,
        'line_form': line_form,
        'active_nav': 'billing',
    })


@login_required
@role_required(*BILLING_ROLES)
def invoice_print(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related('patient').prefetch_related('line_items', 'payments'), pk=pk,
    )
    return render(request, 'billing/invoice_print.html', {'invoice': invoice})
