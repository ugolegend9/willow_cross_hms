from django.contrib import admin
from .models import LabOrder, Sample, LabResult


class SampleInline(admin.StackedInline):
    model = Sample
    extra = 0
    readonly_fields = ('barcode', 'collected_at')


class LabResultInline(admin.StackedInline):
    model = LabResult
    extra = 0
    readonly_fields = ('entered_at',)


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ('test_name', 'patient', 'status', 'ordered_by', 'ordered_at')
    list_filter = ('status', 'test_name')
    inlines = [SampleInline, LabResultInline]
