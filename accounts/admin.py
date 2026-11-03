from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class WCUserAdmin(UserAdmin):
    list_display = ('username', 'staff_id', 'first_name', 'last_name', 'role', 'department', 'is_active')
    list_filter = ('role', 'department', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Hospital info', {'fields': ('staff_id', 'role', 'department', 'phone_number')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Hospital info', {'fields': ('staff_id', 'role', 'department', 'phone_number')}),
    )
