"""
Seeds a realistic demo dataset so the app has something to look at right
after `migrate` — staff logins for every role, patients, wards/beds,
appointments, drugs, and a paid invoice for the dashboard's revenue figure.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --flush   # wipe ALL patient/ward/drug/billing data and reseed
    python manage.py seed_demo_data --force   # allow running with DEBUG off (see below)

This creates staff accounts that all share a publicly known password, so it
refuses to run unless DEBUG is on. --force overrides that; don't use it on a
real system.

Safe to re-run: everything is get_or_create'd, so running it twice won't
create duplicates.
"""
import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, Role
from patients.models import Patient
from ipd.models import Ward, Bed, Admission, CarePlan, MedicationAdministration
from appointments.models import Appointment
from pharmacy.models import Drug, Batch, DispenseRecord
from laboratory.models import LabOrder, Sample, LabResult
from billing.models import Invoice, LineItem, Payment
from ehr.models import Encounter, Vitals, Diagnosis, Allergy
from opd.models import OPDVisit, Prescription

# All demo staff share this password — change it immediately in production.
DEMO_PASSWORD = "changeme123"


class Command(BaseCommand):
    help = "Seed the database with demo staff, patients, beds, appointments, drugs, and billing data."

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true',
                            help='Delete ALL patients, appointments, invoices, wards/beds, drugs and non-superuser '
                                 'accounts before seeding. This is not limited to demo rows.')
        parser.add_argument('--force', action='store_true',
                            help='Run even though DEBUG is off (the demo accounts share a known password).')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError(
                "Refusing to seed: this creates accounts with a publicly known password. "
                "Set DEBUG=True for local development, or pass --force if you really mean it."
            )
        if options['flush']:
            self.stdout.write("Flushing existing demo data…")
            Appointment.objects.all().delete()
            Invoice.objects.all().delete()
            Patient.objects.all().delete()
            Bed.objects.all().delete()
            Ward.objects.all().delete()
            Drug.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()

        staff = self._seed_staff()
        patients = self._seed_patients()
        self._seed_wards_and_beds()
        self._seed_appointments(staff, patients)
        self._seed_pharmacy()
        self._seed_billing(patients)
        self._seed_ehr(staff, patients)
        self._seed_opd(staff, patients)
        self._seed_dispensing(staff, patients)
        self._seed_laboratory(staff, patients)
        self._seed_ipd_admission(staff, patients)

        self.stdout.write(self.style.SUCCESS("\nDemo data ready. Sign in with any of these:"))
        for s in staff:
            self.stdout.write(f"  {s.staff_id:<10} ({s.get_role_display():<16}) — username '{s.username}', password '{DEMO_PASSWORD}'")

    def _seed_staff(self):
        roster = [
            dict(username='aokafor', staff_id='WCH-0001', role=Role.DOCTOR, first_name='Adeyemi', last_name='Okafor', is_superuser=True, is_staff=True),
            dict(username='nbello', staff_id='WCH-0002', role=Role.NURSE, first_name='Ngozi', last_name='Bello'),
            dict(username='cnwosu', staff_id='WCH-0003', role=Role.PHARMACIST, first_name='Chuka', last_name='Nwosu'),
            dict(username='gumeh', staff_id='WCH-0004', role=Role.BILLING, first_name='Grace', last_name='Umeh'),
            dict(username='fadeyemi', staff_id='WCH-0005', role=Role.FRONT_DESK, first_name='Femi', last_name='Adeyemi'),
            dict(username='oyusuf', staff_id='WCH-0006', role=Role.LAB_TECH, first_name='Oyindamola', last_name='Yusuf'),
            dict(username='kchukwu', staff_id='WCH-0007', role=Role.ADMIN, first_name='Kelechi', last_name='Chukwu'),
        ]
        created = []
        for entry in roster:
            is_super = entry.pop('is_superuser', False)
            user, made = User.objects.get_or_create(
                username=entry['username'],
                defaults={**entry, 'is_staff': True, 'is_superuser': is_super},
            )
            if made:
                user.set_password(DEMO_PASSWORD)
                user.save()
            created.append(user)
        self.stdout.write(f"Staff: {len(created)} accounts ready.")
        return created

    def _seed_patients(self):
        roster = [
            dict(first_name='Chidinma', last_name='Eze', date_of_birth=datetime.date(1990, 4, 12), gender='F', blood_group='O+', phone_number='08012345678'),
            dict(first_name='Tunde', last_name='Bakare', date_of_birth=datetime.date(1975, 11, 3), gender='M', blood_group='A+', phone_number='08023456789'),
            dict(first_name='Blessing', last_name='Okoro', date_of_birth=datetime.date(2001, 7, 22), gender='F', blood_group='B+', phone_number='08034567890'),
            dict(first_name='Musa', last_name='Abdullahi', date_of_birth=datetime.date(1988, 2, 15), gender='M', blood_group='O-', phone_number='08045678901'),
        ]
        created = []
        for entry in roster:
            patient, _ = Patient.objects.get_or_create(
                first_name=entry['first_name'], last_name=entry['last_name'],
                date_of_birth=entry['date_of_birth'], defaults=entry,
            )
            created.append(patient)
        self.stdout.write(f"Patients: {len(created)} on file.")
        return created

    def _seed_wards_and_beds(self):
        layout = {
            'Maternity': [('M-01', Bed.Status.AVAILABLE), ('M-02', Bed.Status.OCCUPIED), ('M-03', Bed.Status.AVAILABLE)],
            'General': [('G-01', Bed.Status.AVAILABLE), ('G-02', Bed.Status.OCCUPIED), ('G-03', Bed.Status.MAINTENANCE)],
            'ICU': [('ICU-01', Bed.Status.OCCUPIED), ('ICU-02', Bed.Status.AVAILABLE)],
        }
        count = 0
        for ward_name, beds in layout.items():
            ward, _ = Ward.objects.get_or_create(name=ward_name)
            for bed_number, status in beds:
                _, made = Bed.objects.get_or_create(ward=ward, bed_number=bed_number, defaults={'status': status})
                count += made
        self.stdout.write(f"Wards/beds: {Ward.objects.count()} wards, {Bed.objects.count()} beds.")

    def _seed_appointments(self, staff, patients):
        doctor = next(s for s in staff if s.role == Role.DOCTOR)
        now = timezone.now()
        slots = [now.replace(hour=9, minute=30, second=0, microsecond=0),
                 now.replace(hour=11, minute=0, second=0, microsecond=0),
                 now.replace(hour=14, minute=15, second=0, microsecond=0)]
        count = 0
        for patient, slot in zip(patients, slots):
            _, made = Appointment.objects.get_or_create(
                patient=patient, doctor=doctor, scheduled_for=slot,
                defaults={'department': 'General'},
            )
            count += made
        self.stdout.write(f"Appointments: {Appointment.objects.count()} on the books.")

    def _seed_pharmacy(self):
        today = timezone.localdate()
        # (drug fields, [(batch_number, quantity, expiry_date), ...]) -- varied
        # on purpose so the inventory screen shows a healthy drug, a low-stock
        # one, and one with a batch expiring soon, not three identical rows.
        catalog = [
            (dict(name='Amoxicillin', strength='250mg', unit_price=350, reorder_level=50),
             [('AMO-2026-01', 200, today + datetime.timedelta(days=300))]),
            (dict(name='Paracetamol', strength='500mg', unit_price=100, reorder_level=100),
             [('PAR-2026-01', 150, today + datetime.timedelta(days=300)),
              ('PAR-2026-02', 20, today + datetime.timedelta(days=20))]),  # expiring soon
            (dict(name='Metformin', strength='500mg', unit_price=200, reorder_level=40),
             [('MET-2026-01', 15, today + datetime.timedelta(days=300))]),  # below reorder_level
        ]
        for fields, batches in catalog:
            drug, _ = Drug.objects.get_or_create(name=fields['name'], strength=fields['strength'], defaults=fields)
            for batch_number, quantity, expiry in batches:
                Batch.objects.get_or_create(drug=drug, batch_number=batch_number, defaults={'quantity': quantity, 'expiry_date': expiry})
        self.stdout.write(f"Pharmacy: {Drug.objects.count()} drugs stocked.")

    def _seed_dispensing(self, staff, patients):
        pharmacist = next(s for s in staff if s.role == Role.PHARMACIST)
        paracetamol = Drug.objects.get(name='Paracetamol')
        # A walk-in dispense, not tied to any prescription -- shows dispensing
        # history exists independently of OPD. The seeded OPD prescription
        # (Amoxicillin, above) is deliberately left undispensed so the
        # pharmacy queue isn't empty in the demo.
        if not DispenseRecord.objects.filter(patient=patients[0], drug=paracetamol, prescription__isnull=True).exists():
            DispenseRecord.objects.create(drug=paracetamol, patient=patients[0], quantity=10, dispensed_by=pharmacist)
        self.stdout.write(f"Dispensing: {DispenseRecord.objects.count()} record(s) on file.")

    def _seed_laboratory(self, staff, patients):
        doctor = next(s for s in staff if s.role == Role.DOCTOR)
        tech = next(s for s in staff if s.role == Role.LAB_TECH)

        if not LabOrder.objects.filter(patient=patients[0], test_name='Full Blood Count').exists():
            LabOrder.objects.create(patient=patients[0], ordered_by=doctor, test_name='Full Blood Count')

        if not LabOrder.objects.filter(patient=patients[2], test_name='Urea & Electrolytes').exists():
            order = LabOrder.objects.create(patient=patients[2], ordered_by=doctor, test_name='Urea & Electrolytes',
                                             status=LabOrder.Status.SAMPLE_COLLECTED)
            Sample.objects.create(lab_order=order, collected_by=tech)

        if not LabOrder.objects.filter(patient=patients[3], test_name='Malaria Parasite Test').exists():
            order = LabOrder.objects.create(patient=patients[3], ordered_by=doctor, test_name='Malaria Parasite Test',
                                             status=LabOrder.Status.RESULTED)
            Sample.objects.create(lab_order=order, collected_by=tech)
            LabResult.objects.create(lab_order=order, value='Positive', is_abnormal=True, entered_by=tech,
                                      notes='Plasmodium falciparum seen on film')

        self.stdout.write(f"Laboratory: {LabOrder.objects.count()} order(s) on file.")

    def _seed_billing(self, patients):
        paid, made = Invoice.objects.get_or_create(patient=patients[0], status=Invoice.Status.PAID)
        if made:
            LineItem.objects.create(invoice=paid, description='Antenatal consultation', amount=15000)
            LineItem.objects.create(invoice=paid, description='Lab panel', amount=8500)
            Payment.objects.create(invoice=paid, amount=23500, method=Payment.Method.TRANSFER)

        partial, made2 = Invoice.objects.get_or_create(patient=patients[1], status=Invoice.Status.PARTIAL)
        if made2:
            LineItem.objects.create(invoice=partial, description='Ward bed charge (3 nights)', amount=90000)
            LineItem.objects.create(invoice=partial, description='Medication', amount=12000)
            Payment.objects.create(invoice=partial, amount=50000, method=Payment.Method.CASH)

        unpaid, made3 = Invoice.objects.get_or_create(patient=patients[2], status=Invoice.Status.UNPAID)
        if made3:
            LineItem.objects.create(invoice=unpaid, description='Consultation fee', amount=5000)

        self.stdout.write(f"Billing: {Invoice.objects.count()} invoice(s) on file.")

    def _seed_ehr(self, staff, patients):
        doctor = next(s for s in staff if s.role == Role.DOCTOR)
        patient = patients[0]
        encounter, made = Encounter.objects.get_or_create(
            patient=patient, clinician=doctor, reason='Routine antenatal checkup',
        )
        if made:
            Vitals.objects.create(encounter=encounter, temperature_c=37.1, blood_pressure='118/76', pulse_bpm=80, spo2_percent=98)
            Diagnosis.objects.create(encounter=encounter, description='Normal antenatal findings')
        Allergy.objects.get_or_create(patient=patient, substance='Penicillin', defaults={'reaction': 'Rash', 'severity': 'SEVERE'})
        self.stdout.write(f"EHR: {Encounter.objects.count()} encounter(s), {Allergy.objects.count()} allergy record(s).")

    def _seed_opd(self, staff, patients):
        doctor = next(s for s in staff if s.role == Role.DOCTOR)
        patient = patients[1]
        chief_complaint = 'Persistent cough and mild fever'
        if not OPDVisit.objects.filter(patient=patient, doctor=doctor, chief_complaint=chief_complaint).exists():
            encounter = Encounter.objects.create(patient=patient, clinician=doctor, reason=chief_complaint)
            visit = OPDVisit.objects.create(patient=patient, doctor=doctor, encounter=encounter, chief_complaint=chief_complaint)
            Prescription.objects.create(opd_visit=visit, drug_name='Amoxicillin', dosage='250mg', frequency='3x daily', duration_days=7)
        self.stdout.write(f"OPD: {OPDVisit.objects.count()} visit(s) on file.")

    def _seed_ipd_admission(self, staff, patients):
        doctor = next(s for s in staff if s.role == Role.DOCTOR)
        nurse = next(s for s in staff if s.role == Role.NURSE)
        plan = [
            (Bed.objects.get(ward__name='Maternity', bed_number='M-02'), patients[2], 'Post-partum recovery, day 2'),
            (Bed.objects.get(ward__name='ICU', bed_number='ICU-01'), patients[3], 'Severe malaria — IV fluids and monitoring'),
            (Bed.objects.get(ward__name='General', bed_number='G-02'), patients[1], 'Pneumonia — IV antibiotics and observation'),
        ]
        for bed, patient, diagnosis in plan:
            if Admission.objects.filter(bed=bed, status=Admission.Status.ADMITTED).exists():
                continue
            admission = Admission.objects.create(
                patient=patient, bed=bed, attending_doctor=doctor, diagnosis_summary=diagnosis,
            )
            CarePlan.objects.create(admission=admission, instructions='Monitor vitals every 4 hours.', created_by=doctor)
            MedicationAdministration.objects.create(admission=admission, drug_name='Paracetamol', dose='1g', administered_by=nurse)
        self.stdout.write(f"IPD: {Admission.objects.filter(status=Admission.Status.ADMITTED).count()} active admission(s).")
