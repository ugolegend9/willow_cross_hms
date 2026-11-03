# Handoff: continuing Willow Cross HMS in Claude Code

This project was built in claude.ai chat, module by module, with a spec doc
and design canvas that live there. This file is the self-contained briefing
so work can continue in Claude Code without needing access to those —
everything essential is repeated here. `README.md` covers setup and what's
built; this file covers how the project is built and what's left.

## What this is

A Django + MySQL Hospital Management System for the Nigerian market
("Willow Cross Hospital" is a placeholder name — swap it via `HOSPITAL_NAME`
in `.env`). The full spec is 28 modules across 5 phases. Phase 1 (the core
MVP — Patients, EHR, Appointments, OPD, IPD, Billing, Pharmacy) is complete.
Phase 2 (clinical depth) is underway: Laboratory is done.

Full spec doc (claude.ai, not reachable from Claude Code):
`https://claude.ai/artifact/a5fb8b39-848c-4d76-994c-0163155a5b0b` — the
module-by-module spec, tech requirements, and the systematic build plan for
everything not yet built are summarized below so it isn't needed day to day.
Design canvas (Login/Dashboard mockups):
`https://claude.ai/artifact/1Nrk2u57AtKm82mHZcpVXS`.

## Status right now

243 tests, all passing, on Django 5.0/5.2/6.1. No migration drift, no lint
issues. Built and working: Patients, EHR, Appointments, OPD, IPD, Billing,
Pharmacy, Laboratory. Not started: everything else in the spec (see the
per-module plan below).

## The build recipe — follow this for every new module

This is the actual sequence every module so far followed. Skipping a step
is how a feature ends up existing in the database but not really working;
several steps below exist specifically because skipping them caused a real
bug earlier in this project (named inline where relevant).

1. **Models + migration** — `on_delete` chosen deliberately: `PROTECT` for
   anything that's audit/financial history (e.g. `DispenseRecord.drug`,
   fixed after a drug deletion once cascaded away its own dispense
   history), `CASCADE` only for true child records. Add `UniqueConstraint`s
   wherever a duplicate would be a real bug (e.g. two "Amoxicillin 250mg"
   catalog entries), not a theoretical one. Model-level validators too
   (`MinValueValidator`, etc.) — the Django admin bypasses forms entirely,
   so a rule that only lives in a form doesn't apply there.
2. **Permissions** — add the role list to `accounts/permissions.py` (the
   one source of truth) as a module-level tuple, e.g. `LAB_ROLES =
   (Role.LAB_TECH, Role.ADMIN)`. Wire it into the view's `@role_required`
   *and* into `core/context_processors.py`'s `can.*` dict. Never check a
   role any other way.
3. **Forms** — validation that matches reality (positive amounts, plausible
   ranges — see `ehr/forms.py`'s vitals range checks, cross-field rules).
4. **Views** — RBAC-decorated with `@login_required` and `@role_required`.
   Anywhere two staff could race for the same resource (booking a bed,
   dispensing a prescription, entering a lab result, consulting an
   appointment), lock it: `select_for_update()` inside
   `transaction.atomic()`, re-check the status *after* locking, and raise a
   plain `forms.ValidationError` if someone beat you to it — never let a
   `OneToOneField`'s unique constraint surface as a raw `IntegrityError`
   (that's an unhandled 500). Put this lock inside the form's own `save()`,
   not the view — that's what makes it testable without needing two
   genuinely overlapping HTTP requests (Django's test client runs requests
   sequentially, so two sequential `.post()` calls will not reproduce a
   real race; they'll just hit the view's own earlier status check twice).
   See `pharmacy/forms.py:DispenseForm.save()`, `laboratory/views.py`, and
   `opd/forms.py:OPDVisitForm.save()` for three real examples of this exact
   pattern, including one bug found and fixed this way in each module.
5. **URLs**.
6. **Templates** — reuse `static/css/base.css` (deep teal `#14555A`, Sora
   headings, IBM Plex Sans body). Gate every button/link with the matching
   `can.*` flag so the UI never offers what the server would refuse — there
   is a standing test for this (see "The one test to never break," below).
   Always render `{{ form.non_field_errors }}` somewhere, even when every
   individual field already shows its own errors — a `UniqueConstraint`
   violation or a cross-field rule raised in `clean()` has nowhere else to
   display, and a silently-dropped rejection (the user sees nothing happen
   and has no idea why) is a real bug found this way once already.
7. **Cross-links** — wire into the sidebar (`templates/core/app_base.html`),
   dashboard quick actions/KPI cards (`templates/core/dashboard.html`,
   `core/views.py`), and whichever existing module's pages are genuinely
   relevant. The EHR timeline (`templates/ehr/patient_ehr.html`) is where
   this matters most: OPD prescriptions, Pharmacy's Dispensed/Pending
   badge, and Laboratory's orders/results all surface there, because
   that's what "one system of record" means in practice.
8. **Seed data** — update `core/management/commands/seed_demo_data.py`
   every time, as its own `_seed_<module>()` method, called from `handle()`.
   Must stay idempotent (check-before-create, never blind `.create()`) and
   show every state the module can be in, not just the happy path (e.g.
   Pharmacy's seed shows a low-stock drug *and* a drug with a batch
   expiring soon, not just one healthy drug).
9. **Tests** — one per behavior and per RBAC rule, plus a regression test
   for every bug found while building, named so the bug is obvious from the
   test name alone.
10. **Mutation-check** — for each new guard, comment it out (or replace its
    condition with `True`/`False`/`pass`), confirm the matching test goes
    red, then put it back. This has caught tests that looked right but
    didn't actually exercise the guard (see "A mistake worth repeating,"
    below) — don't skip this step even when a test obviously should cover
    something.
11. **Live verification** — run the dev server and exercise the real flow
    end to end, not just `manage.py test`. Real bugs the automated suite
    missed on first pass: a UTC-vs-Lagos date bug, N+1 queries, a POST-only
    endpoint that used to be a GET link.
12. **Visual check** — for anything with a UI, actually render it (a
    headless browser, e.g. Playwright, works well) and look at the
    screenshot. Caught: a wrong HTTP method on logout, an occupied bed with
    no patient in the seed data, a validation error that was computed
    correctly but never displayed, Django's default ugly admin plurals
    ("Allergys", "Diagnosiss") on model names that need an explicit
    `Meta.verbose_name_plural`.
13. **Docs** — update `README.md` (what's working, test count, known gaps)
    and the spec doc's build-status checklist (claude.ai only).

### The one test to never break

`core/test_regressions.py:UIMatchesServerPermissionsTests` checks, for
every one of the 7 roles and for a superuser, that every button/link shown
on the dashboard and patient-profile pages is one the server will actually
allow for that role — and that the reverse holds too (nothing the server
allows is hidden without reason). When adding a new cross-link in step 7
above, add its probe to this test's `_cases()` method in the same change.

### A mistake worth repeating (so it doesn't get repeated by accident)

More than once, a "concurrent dispense/result/consult" test used two
sequential `self.client.post()` calls and looked like it tested a race —
but Django's test client fully commits the first request before the second
one starts, so it only ever exercised the view's *earlier* sequential
status check, never the actual lock. The fix each time: bypass the view and
call the form's `save()` directly, twice, so both calls genuinely see the
pre-lock state before either commits. See
`opd/tests.py:ConcurrentConsultTests` for the clearest example and the
comment explaining why the sequential version next to it doesn't count.

## What's built (Phase 1 complete, Phase 2 underway)

| Module | State |
|---|---|
| Patients | ✅ registration (Front Desk/Admin only), search, detail, auto-MRN |
| EHR | ✅ encounter timeline, vitals (range-checked), allergies, diagnoses |
| Appointments | ✅ booking, status flow (server-enforced), today/upcoming/past |
| OPD | ✅ queue, consultation (chief complaint + prescription + referral) |
| IPD | ✅ bed map, admission, care plans, MAR, discharge, bed/ward management |
| Billing | ✅ invoices (unlimited line items via JS), payments, printable invoice |
| Pharmacy | ✅ queue, dispensing (FEFO, allergy gate), inventory |
| Laboratory | ✅ queue, order/collect/result (auto-abnormal detection), cancel |
| Everything else | ⬜ not started — see the plan below |

Dashboard, patient-profile buttons, and sidebar nav are all wired per-module
and role-gated (`can.*` flags). `accounts.Role` currently has 7 values:
Admin, Doctor, Nurse, Pharmacist, Lab Technician, Billing Officer, Front
Desk — see "Open decisions," below, before adding more.

## The plan for everything not yet built

### Phase 2 — remaining
- **Operation Theatre** (`ot`) — Models: `Surgery`, `OTSchedule`,
  `ConsentForm`. Screens: OT schedule, pre-op checklist + consent capture,
  surgical team assignment, post-op notes. Roles: Surgeon, Anesthetist, OT
  Nurse, Admin (new roles — see below). Integrates with: Patients, IPD (a
  surgery usually brackets an admission), EHR (post-op notes in the
  timeline, like OPD prescriptions and Lab results already do).
- **Radiology & PACS** (`radiology`) — Models: `ImagingOrder`,
  `RadiologyReport`, `StudyFile` (an uploaded image/file — a real DICOM
  viewer needs a dedicated PACS server, out of scope here). Screens:
  imaging queue, report entry with file attachment. Roles: Radiologist,
  Technician, Doctor. Integrates with: OPD/IPD, EHR, Billing.
- **Nursing Management** (extend `ipd`, since MAR already lives there) —
  Models: `NursingTask`, `HandoverNote`. Screens: a nurse's task list per
  ward/shift, shift handover notes. Roles: Nurse, Admin.
- **Emergency & Trauma** (`emergency`) — Models: `EmergencyCase`,
  `TriageScore`. Screens: a severity-sorted ER triage board. Reuse
  `ipd.Bed`/`Ward` (tag a ward "ER") rather than a parallel bed concept.
  Roles: ER Doctor, Nurse, Dispatcher, Admin. Ambulance dispatch waits for
  Phase 4's Fleet module.

### Phase 3 — Operations & finance
- **Inventory & Supply Chain** (`inventory`) — `StockItem` (non-drug
  consumables, distinct from `pharmacy.Drug`), `PurchaseOrder`, `Vendor`.
  Same UI pattern as Pharmacy's inventory page. Roles: Store Manager, Admin.
- **Insurance & Claims** (extend `billing`) — `InsuranceClaim`,
  `TPAProvider`. Submit a claim from an existing Invoice. Uses
  `patients.InsurancePolicy`, which already exists and nothing reads yet.
  Roles: Billing Officer, Admin.
- **Human Resources** (`hr`) — `StaffProfile` (or extend `accounts.User`),
  `Shift`, `PayrollRecord`. Roster calendar, payroll list, credentials.
  Roles: HR Manager, Admin.
- **Blood Bank** (`bloodbank`) — `Donor`, `BloodUnit`, `CrossMatch`. Donor
  registry, inventory by blood type, cross-match. Roles: Blood Bank
  Officer, Admin.

### Phase 4 — Extended services
- **Ambulance & Fleet** (`fleet`) — `Vehicle`, `DispatchLog`. Roles:
  Dispatcher, Driver, Admin. Link back to Emergency's dispatch once both exist.
- **Diet & Catering** (`catering`) — `DietPlan`, `MealOrder`. Diet plans
  pull from `ehr.Allergy` (same data Pharmacy's allergy gate already
  reads). Roles: Dietitian, Kitchen Staff, Admin.
- **Housekeeping & Facility** (`facility`) — `CleaningTask`,
  `MaintenanceLog`. Ties into `ipd.Bed`/`Ward`. Roles: Facility Manager, Admin.
- **Medical Records archive** (extend `ehr`/`patients`) — `Document`,
  `AccessLog`. The access log can double as the start of Security's
  audit-logging requirement rather than being built twice.

### Phase 5 — Scale & intelligence
- **Analytics & BI** (extend `core`) — occupancy/revenue/patient-flow
  trends over time, a filter-and-export-CSV report builder, beyond the
  current dashboard KPI cards.
- **Patient Portal** (`portal`) — **needs a decision first**: patients
  logging in is a second, separate auth flow from `accounts.User` (staff),
  not just a new role — a patient must never see another patient's record
  or anything staff-only.
- **Telemedicine** (`telemedicine`) — `VideoConsultation` linking an
  `Appointment` to a session. Real video calling needs a third-party embed
  (Jitsi/Twilio) — out of scope for plain Django.
- **Security, finishing the partial parts** — 2FA (`django-otp`), field-
  level encryption for diagnoses/results/financials, audit logging (reuse
  Medical Records' `AccessLog`, or a dedicated signal-fed `AuditLog`).
- **Interoperability (HL7/FHIR)** — REST endpoints (Django REST Framework)
  exposing Patient/Encounter/LabResult as FHIR-shaped JSON. Large and
  specialized — a stretch goal, not a weekend addition.
- **Multi-Facility Administration** (extend `core`) — a `Facility` model
  FK'd onto Patient/Ward/Invoice/etc. This touches nearly every existing
  app's schema — plan it as its own dedicated pass, ideally sooner rather
  than later (cheaper before more modules pile on top).
- **Quality & Compliance** (`quality`) — `IncidentReport`, `SafetyEvent`.
- **Notifications** (`notifications`, cross-cutting) — `Notification`.
  Start as in-app only; real SMS/email (Termii, per the spec) is a paid
  external service and a separate decision.

## Open decisions before some of these can start

- **New roles**: the spec names 15 more (Surgeon, Anesthetist, OT Nurse, ER
  Doctor, Dispatcher, Driver, Store Manager, HR Manager, Blood Bank
  Officer, Dietitian, Kitchen Staff, Facility Manager, Records Officer,
  Management, Quality Officer). Decide per-module whether a new `Role` is
  warranted or an existing one (often Nurse or Admin) covers it — adding
  every one verbatim would fragment RBAC for roles used by one screen each.
- **Patient-facing login** (Portal, Telemedicine) is architecturally
  different from everything built so far, which is staff-only. Plan this
  as its own session, not an incremental add onto an existing view.
- **Multi-Facility Administration** touches nearly every table. Earlier is
  cheaper than later.
- **Scope limits worth naming now**: no real DICOM viewer, no real video
  calling, no real SMS/email delivery, and "HL7/FHIR" realistically means
  FHIR-shaped JSON export, not full conformance. Each is a genuine external
  integration or a different kind of project, not a Django feature.

## Known gaps (unchanged, tracked in README too)

No audit logging, no 2FA, no login rate-limiting, no pagination on long
lists (silently stop at 100/200 rows), no check for a doctor being
double-booked, no UI to edit/deactivate a drug once added (use `/admin/`).

## Quick reference

```bash
cp .env.example .env            # DB_ENGINE=sqlite for zero-setup local work
python manage.py migrate
python manage.py seed_demo_data # 7 staff logins printed at the end, password changeme123
python manage.py test           # 243 tests, a couple of seconds
python manage.py runserver
```

`accounts/permissions.py` is the single source of truth for who can do
what — read it first in any new session; it's short and tells you more
about the system's shape than anything else in the codebase.
