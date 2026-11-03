from django.contrib import admin
from .models import Ward, Bed, Admission, CarePlan, MedicationAdministration


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ('ward', 'bed_number', 'status')
    list_filter = ('ward', 'status')


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'bed', 'attending_doctor', 'status', 'admitted_at')
    list_filter = ('status',)


admin.site.register(Ward)
admin.site.register(CarePlan)
admin.site.register(MedicationAdministration)
