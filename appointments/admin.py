from django.contrib import admin
from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'scheduled_for', 'department', 'status')
    list_filter = ('status', 'department')
    date_hierarchy = 'scheduled_for'
