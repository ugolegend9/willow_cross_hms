from django.contrib import admin
from .models import Invoice, LineItem, Payment


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 1


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'status', 'total', 'amount_paid', 'balance', 'created_at')
    inlines = [LineItemInline, PaymentInline]
