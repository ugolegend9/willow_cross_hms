"""
Who may do what. Both the view decorators and the templates read from here, so
the interface can only offer what the server will actually allow. If a role
list changes, it changes in exactly one place.
"""
from .models import Role

EHR_ROLES = (Role.DOCTOR, Role.NURSE, Role.ADMIN)          # open a patient's record
CONSULT_ROLES = (Role.DOCTOR, Role.ADMIN)                  # run an OPD consultation
ADMIT_ROLES = (Role.DOCTOR, Role.ADMIN)                    # admit / discharge
IPD_CLINICAL_ROLES = (Role.DOCTOR, Role.NURSE, Role.ADMIN) # view an admission, log care
BILLING_ROLES = (Role.BILLING, Role.ADMIN)                 # everything in Billing
BOOKING_ROLES = (Role.FRONT_DESK, Role.DOCTOR, Role.NURSE, Role.ADMIN)  # book / update appointments
BED_MANAGEMENT_ROLES = (Role.ADMIN,)                       # add wards/beds, set maintenance
REGISTER_PATIENT_ROLES = (Role.FRONT_DESK, Role.ADMIN)     # create a new patient record
PHARMACY_ROLES = (Role.PHARMACIST, Role.ADMIN)             # dispensing, inventory, the pharmacy queue
LAB_ROLES = (Role.LAB_TECH, Role.ADMIN)                    # the lab queue, sample collection, result entry
LAB_ORDER_ROLES = (Role.DOCTOR, Role.ADMIN)                # ordering (and cancelling) a lab test
# Financial visibility follows who can use Billing at all -- a distinct name
# because "can see revenue" and "can use the Billing screens" happen to be the
# same roles today but are different questions, and may not stay linked.
REVENUE_ROLES = BILLING_ROLES


def has_role(user, roles):
    """True if the user may act as one of `roles`. Superusers may do anything."""
    return bool(user.is_authenticated and (user.is_superuser or user.role in roles))
