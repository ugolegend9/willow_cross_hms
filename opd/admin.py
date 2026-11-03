from django.contrib import admin
from .models import OPDVisit, Prescription, Referral


class PrescriptionInline(admin.TabularInline):
    model = Prescription
    extra = 1


@admin.register(OPDVisit)
class OPDVisitAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'chief_complaint', 'visited_at')
    inlines = [PrescriptionInline]


admin.site.register(Referral)
