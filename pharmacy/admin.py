from django.contrib import admin
from .models import Drug, Batch, DispenseRecord


class BatchInline(admin.TabularInline):
    model = Batch
    extra = 1


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ('name', 'strength', 'unit_price', 'total_stock', 'reorder_level', 'is_controlled')
    inlines = [BatchInline]


@admin.register(DispenseRecord)
class DispenseRecordAdmin(admin.ModelAdmin):
    list_display = ('drug', 'patient', 'quantity', 'dispensed_by', 'dispensed_at')
    list_filter = ('drug',)
