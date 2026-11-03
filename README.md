# Willow Cross HMS — Phase 1

Django + MySQL hospital management system. Phase 1 modules: Accounts (RBAC),
Patients, EHR, Appointments, OPD, IPD, Pharmacy, Billing, and a live Dashboard —
matching the spec doc and the Login/Dashboard mockups already designed.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env            # then edit DB_* values for your MySQL server
```

If you don't have MySQL running yet, set `DB_ENGINE=sqlite` in `.env` for a
zero-setup local run — the code doesn't change either way.

```bash
python manage.py migrate
python manage.py seed_demo_data     # staff logins for every role + demo patients/beds/appointments
python manage.py runserver
```

`seed_demo_data` prints out a working login for all 7 roles when it finishes
(all use password `changeme123` — change it before this goes anywhere real).
Safe to re-run; it won't create duplicates. `--flush` deletes **all** patients,
appointments, invoices, wards/beds, drugs and non-superuser accounts before
reseeding (it isn't limited to demo rows). Because the demo accounts share a
known password, the command refuses to run unless `DEBUG=True` (pass `--force`
to override; never do that on a real system).

| Staff ID | Role | Username |
|---|---|---|
| WCH-0001 | Doctor (also superuser, for `/admin/`) | `aokafor` |
| WCH-0002 | Nurse | `nbello` |
| WCH-0003 | Pharmacist | `cnwosu` |
| WCH-0004 | Billing Officer | `gumeh` |
| WCH-0005 | Front Desk | `fadeyemi` |
| WCH-0006 | Lab Technician | `oyusuf` |
| WCH-0007 | Administrator | `kchukwu` |

Visit `http://127.0.0.1:8000/` — you'll land on the login screen, then the
live dashboard (patient counts, bed availability, today's appointments, and
revenue all pull from the database).

## Configuration

`DEBUG` defaults to **off**; `.env.example` turns it on for local work. With
`DEBUG` off the app refuses to start on the placeholder `SECRET_KEY`, so a
deployment that forgot to configure anything fails loudly instead of running
with a publicly known key. Don't commit or ship your `.env` (it's in `.gitignore`).

With `DEBUG` off the app also switches on HTTPS-only behaviour: redirect to
HTTPS, secure session/CSRF cookies, and HSTS (starting at one hour, so a
mistake is cheap; raise `SECURE_HSTS_SECONDS` once HTTPS is confirmed working).
Set `BEHIND_PROXY=True` if a reverse proxy terminates TLS. `manage.py check
--deploy` still reports two warnings (HSTS subdomains and preload); those are
left for you to decide because they affect every subdomain of your domain.

## Permissions

Who may do what lives in one file, `accounts/permissions.py`. The view
decorators and the templates (`{% if can.billing %}`, via
`core/context_processors.py`) both read from it, so the interface can't offer
a button the server would refuse. To change who can do something, change it
there and nothing else; a test fails if the two ever drift apart.

## Project layout

- `config/` — settings, root urls
- `accounts/` — custom User model with `role` (Doctor/Nurse/Pharmacist/Lab
  Tech/Billing/Front Desk/Admin) and an `@role_required(...)` decorator for RBAC
- `patients/` — Patient master index, MRN auto-generation, next of kin, insurance
- `ehr/` — Encounter, Vitals, Allergy, Diagnosis, ClinicalNote
- `appointments/` — Appointment scheduling
- `opd/` — OPD visit, prescriptions, referrals
- `ipd/` — Wards, beds, admissions, care plans, medication administration
- `pharmacy/` — Drug catalog, batches/expiry, dispense records
- `billing/` — Invoices, line items, payments
- `core/` — Dashboard view + shared template shell (sidebar/topbar)
- `templates/`, `static/css/base.css` — the look from the Design canvas
  (deep teal `#14555A`, Sora + IBM Plex Sans), reused as real Django templates

## What's already working

- **Admin panel** (`/admin/`) — a link appears in the sidebar for superusers
  only; the Administrator *role* on its own has no permissions there and
  manages beds/wards through the app instead (see below)

- **Login / logout / change password** (Django auth, `accounts.User`), with
  role-based access on every clinical and financial screen
- **Dashboard** — live counts: patients registered today, bed availability,
  today's appointments, and revenue (payments actually received today,
  shown only to roles with Billing access)
- **Patients** — registration (Front Desk/Admin only), search (by MRN or full
  name, either order, open to every role), detail view, auto-generated MRNs
  (`WCH-<year>-<sequence>`)
- **EHR** — encounter timeline, vitals (range-checked), diagnoses, notes, allergy banner
- **Appointments** — booking, today/upcoming/past views, a server-enforced
  Scheduled → Checked in → Completed flow
- **OPD** — queue of checked-in patients, consultation with prescription and
  referral, linked into the patient's EHR
- **IPD** — bed map, admission (no double admissions or double-booked beds),
  care plans, medication administration record, discharge, and a beds/wards
  management screen (Administrator role) to add wards, add beds in bulk, mark
  a bed under maintenance, and remove an unused bed
- **Billing** — invoices with any number of line items (add more with the
  "+ Add another line" button, remove with the × — no fixed limit),
  payments with balance checks,
  Unpaid → Partial → Paid status kept in sync automatically (including from
  the admin), ₦ amounts with thousands separators, a printable invoice
  (`/billing/<id>/print/`, a clean one-page layout with a Print/Save-as-PDF
  button), and adding a charge to an invoice after it's created
- **Pharmacy** — pending-prescriptions queue, dispensing (FEFO stock
  deduction, allergy check with acknowledgement gate, dispense-from-
  prescription or a walk-in), inventory (add a drug, receive stock, low-stock
  and expiring-soon badges), a dashboard KPI for low-stock drugs, and a
  Dispensed/Pending badge on each prescription in the patient's EHR timeline
- **Laboratory** — order a test from the patient profile, a two-section
  queue (awaiting sample collection / awaiting result), barcoded sample
  collection, result entry with auto-abnormal detection when the value and
  reference range are both plain numbers, cancellation of a pending order,
  a dashboard KPI for pending results, and lab orders/results shown in the
  patient's EHR timeline
- **Django admin** (`/admin/`) for every model

## Running the tests

```bash
python manage.py test
```

243 tests across every built module, using Django's test runner (a throwaway
test database, not your real one). The whole suite runs in a couple of seconds:

- `accounts` — login/logout flow, `@role_required` decorator (allowed role,
  disallowed role → 403, superuser bypass, anonymous → denied)
- `patients` — MRN auto-generation (format + sequence, stable on resave),
  list/search, registration (success + validation error), detail view
- `ehr` — RBAC (clinical roles only), combined encounter form (creates
  linked Vitals/Diagnosis together, skips Vitals when none given, validation
  errors surface), allergy banner
- `appointments` — RBAC (booking roles only, others can still view),
  booking, full status flow (Scheduled → Checked in → Completed), invalid
  status values ignored, today/upcoming/past scope filters
- `core` — dashboard access control and that its KPI numbers actually match
  what's in the database (not just that the page loads)
- `opd` — RBAC (Doctor/Admin only consult, anyone logged in can view the
  queue), checked-in patients appear/disappear from the queue correctly,
  consultation creates a linked EHR encounter, prescription and referral
  cross-field validation, consulting from an appointment auto-completes it,
  and the prescription shows up in the patient's EHR timeline
- `ipd` — RBAC (Doctor/Admin admit & discharge, clinical roles view
  admission detail, anyone logged in views the bed map), admitting a
  patient marks the bed occupied and only offers available beds, care
  plan/MAR entries can be added, discharge frees the bed and is POST-only
  and role-restricted, bed map correctly reflects occupancy
- `billing` — RBAC (Billing/Admin only, everyone else forbidden — note that
  a superuser account always bypasses role checks by design), invoice
  creation via the line-item formset (blank rows skipped, no patient means
  no invoice), payment validation (rejects zero/negative and overpayment),
  and that status actually transitions Unpaid → Partial → Paid as real
  payments accumulate

- `core/test_regressions.py` — one test per bug found in the build audit
  (revenue counting, Lagos-vs-UTC "today", full-name search, double admissions,
  appointment status flow, vitals ranges, invoice validation, seed-command
  safety, and more). If one of these goes red, an old bug has come back. The
  second audit added: invoice status staying correct however payments change,
  MRN collision handling, a check that page cost does not grow with row count
  (no N+1 queries), production security settings, and a check that **every
  button and link shown to a role is one the server will actually allow**.
  A third pass added: adding a charge to an existing invoice, printing an
  invoice, and adding/managing wards and beds — each checked for its role
  restrictions, its edge cases (a void invoice can't be changed, an occupied
  bed can't be removed), and, for the print view, actually rendered in a
  headless browser and converted to a real PDF to check the page layout. A
  fourth pass locked down three access decisions: patient registration is
  Front Desk/Admin only, dashboard revenue is only shown to roles that can
  use Billing, and every role can change their own password. A fifth pass
  built Pharmacy dispensing: FEFO stock deduction (oldest-expiring batch
  used first), expired batches excluded from both available stock and the
  deduction itself (checked as two separate things, since the first can
  mask a bug in the second), a dispense-from-prescription flow guarded
  against patient mismatches, an allergy-acknowledgement gate that only
  appears when the patient actually has an allergy on file, and a
  concurrency check that two pharmacists dispensing the same stock at once
  can't oversell it. A sixth pass found: deleting a drug from the catalog
  used to cascade-delete its entire dispensing history (now PROTECTed, like
  an invoice or a lab result); no uniqueness check on the drug catalog or
  batch numbers (duplicate "Amoxicillin 250mg" entries were possible, now
  rejected -- and the rejection message was initially silently dropped by
  the template, since it's a non-field error, not tied to one input); a
  whitespace-only prescription name could crash the dispense page; and the
  prescription-dispense race was closed with a row lock, turning a raw
  database error into a clean, catchable one. Laboratory (the first Phase 2
  module) applied every one of these lessons from the start rather than
  rediscovering them: `PROTECT` on history-bearing foreign keys, a
  collision-safe barcode generator (same pattern as the patient MRN), a row
  lock around result entry so two techs can't double-enter a result, and a
  non-field error rendered on every form from day one. A fourth pass,
  auditing OPD specifically, found the same double-action bug class one
  module earlier than Pharmacy or Laboratory: a cancelled or already-
  completed appointment could still be consulted, silently creating a
  duplicate OPDVisit/Encounter/Prescription. Fixed the same way, and moved
  the lock into the form's own `save()` so the fix is independently
  testable rather than only reachable through two full HTTP requests
  (Django's test client runs requests sequentially, so two sequential
  `.post()` calls don't actually test a real race — they test the same
  thing twice. Testing the critical section directly, the way pharmacy's
  and lab's concurrency tests already did, was necessary to catch this).

Keep this suite growing alongside `seed_demo_data` as new modules get built.

See `HANDOFF.md` for the full build methodology, per-module plan for
everything remaining, and open design decisions — written to be
self-contained for continuing this project in Claude Code.

## What's next

Phase 1 is complete. Laboratory (Phase 2) is done. Remaining in Phase 2:
Operation Theatre, Radiology, Nursing Management, Emergency & Trauma. The
spec doc's "Systematic build plan" section has a concrete plan (models,
screens, roles, integration points) for every one of these and everything
in Phases 3-5.

Known gaps worth knowing about before this goes near real patients: no audit
logging, no 2FA, no login rate-limiting, no
pagination on long lists (they silently stop at 100/200 rows), no check for
a doctor being double-booked, and no UI to edit or deactivate a drug once
added (use /admin/ for that).

## Note on MySQL locally

`requirements.txt` installs `PyMySQL`, a pure-Python MySQL driver — no OS
build tools needed, `pip install -r requirements.txt` just works on a fresh
machine. `config/settings.py` calls `pymysql.install_as_MySQLdb()` so Django
uses it transparently; nothing else needs to know which driver is active.

`mysqlclient` is faster and fine to swap in for production, but it needs
`libmysqlclient-dev` (Linux) or `mysql-client` (macOS via Homebrew) installed
at the OS level *before* `pip install` will build it — it's commented out in
requirements.txt on purpose so a fresh clone never fails to install over
this. Only uncomment it once those build tools are actually in place.
