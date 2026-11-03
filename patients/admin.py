from django.contrib import admin
from .models import Patient, NextOfKin, InsurancePolicy


class NextOfKinInline(admin.TabularInline):
    model = NextOfKin
    extra = 1


class InsurancePolicyInline(admin.TabularInline):
    model = InsurancePolicy
    extra = 1


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('mrn', 'full_name', 'gender', 'date_of_birth', 'phone_number', 'registered_at')
    search_fields = ('mrn', 'first_name', 'last_name', 'phone_number')
    list_filter = ('gender', 'blood_group')
    inlines = [NextOfKinInline, InsurancePolicyInline]
