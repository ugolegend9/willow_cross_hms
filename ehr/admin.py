from django.contrib import admin
from .models import Encounter, Vitals, Allergy, Diagnosis, ClinicalNote

admin.site.register(Encounter)
admin.site.register(Vitals)
admin.site.register(Allergy)
admin.site.register(Diagnosis)
admin.site.register(ClinicalNote)
