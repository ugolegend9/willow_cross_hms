from django.conf import settings

from accounts import permissions as p


def ui_permissions(request):
    """Expose what the current user may do as `can.<action>`, and the hospital's
    identity as `hospital`, to every template."""
    user = request.user
    return {
        'can': {
            'view_ehr': p.has_role(user, p.EHR_ROLES),
            'consult': p.has_role(user, p.CONSULT_ROLES),
            'admit': p.has_role(user, p.ADMIT_ROLES),
            'view_admission': p.has_role(user, p.IPD_CLINICAL_ROLES),
            'billing': p.has_role(user, p.BILLING_ROLES),
            'book': p.has_role(user, p.BOOKING_ROLES),
            'manage_beds': p.has_role(user, p.BED_MANAGEMENT_ROLES),
            'register_patient': p.has_role(user, p.REGISTER_PATIENT_ROLES),
            'pharmacy': p.has_role(user, p.PHARMACY_ROLES),
            'lab': p.has_role(user, p.LAB_ROLES),
            'order_lab': p.has_role(user, p.LAB_ORDER_ROLES),
            'view_revenue': p.has_role(user, p.REVENUE_ROLES),
            # The Django admin bypasses the app's business rules, so only
            # superusers are pointed at it.
            'admin_site': bool(user.is_authenticated and user.is_superuser and user.is_staff),
        },
        'hospital': {
            'name': settings.HOSPITAL_NAME,
            'address': settings.HOSPITAL_ADDRESS,
            'phone': settings.HOSPITAL_PHONE,
        },
    }
