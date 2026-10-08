# Sewa Setu — Old Age Pension Portal

Sewa Setu is a Flask and PostgreSQL portal for the Government of Purvanchal's
Old Age Pension Scheme. Citizens verify their mobile number, complete a
multi-step application, upload age proof, submit the application, and track
its status. Department staff can review applications through the admin portal.

This submission focuses on evidence-led fixes to citizen safety, statutory
processing, data integrity, and production reliability.

## What was fixed

- **Secure uploads:** JPG/JPEG/PDF signature checks, 5 MB limit, safe generated
  storage names, and protection against path traversal and extension spoofing.
- **Names and eligibility:** Unicode-safe names, Unicode PDF output, strict
  `DD/MM/YYYY` dates, India-time age validation, and exactly-60 eligibility.
- **Duplicate prevention:** A database uniqueness constraint ensures one
  application per verified mobile number, including concurrent submissions.
- **Statutory deadlines:** The application window closes at midnight IST.
  Untouched applications are deemed approved after 15 days and shown as
  approved to citizens immediately.
- **Citizen corrections:** Applicants can edit a pending application within
  the 15-day processing window. Approved, rejected, deemed-approved, and
  overdue applications are locked.
- **Performance:** A bounded PostgreSQL connection pool, SLA query index, and
  lighter PDF generation address month-end connection exhaustion and timeouts.
- **Data protection:** The public SMS inbox proxy was removed, application
  ownership checks were added, PDFs require authorization, password reset was
  secured with SMS verification, and admin actions require admin authorization.
- **Secret management:** Flask, admin, and database secrets are supplied
  through the deployment environment rather than committed source.

Detailed evidence and implementation notes are in [fixes/](./fixes/).
The presentation-ready overview is [FIXES_SUMMARY.md](./fixes/FIXES_SUMMARY.md).

## Repository layout

```text
app/
  app.py                         Flask application
  application_validation.py      Shared date, age, and Unicode validation
  upload_validation.py            Upload type and size validation
  schema.sql                      PostgreSQL schema and indexes
  scripts/deemed_approval.py      15-day deemed-approval job
  templates/                      Citizen and admin pages
  tests/                          Focused regression tests
smsgw/                             Internal simulated SMS gateway
seed/                              Supplied production seed data
fixes/                             Fix documentation and Loom summary
docker-compose.yml                 Local and EC2 deployment
```

## Run locally

### Prerequisites

- Docker Engine
- Docker Compose v2

Create local secrets before starting:

```bash
cp .env.example .env
```

Replace every placeholder in `.env` with non-committed values. For a local
test deployment, a generated secret and strong development passwords are
sufficient.

Start the stack:

```bash
docker compose up -d --build
docker compose ps
```

The portal is available at:

```text
http://localhost:8000
```

The simulated SMS gateway is intentionally **not** exposed through the public
portal. The application communicates with it over Docker's private network.
Its messages are in-memory and are cleared when the gateway container
restarts.

## Production deployment

On the EC2 host:

```bash
git pull origin master
cp .env.example .env       # first deployment only
nano .env
docker compose up -d --build
docker compose ps
```

Set these values in `.env`:

```env
SEWA_SECRET_KEY=<long-random-Flask-session-secret>
SEWA_ADMIN_USERNAME=<department-admin-username>
SEWA_ADMIN_PASSWORD=<long-random-admin-password>
SEWA_DB_PASSWORD=<PostgreSQL-password>
```

Use a secret manager or protected server file for production values. Never
commit `.env`.

### Existing PostgreSQL volume

The files mounted under `docker-entrypoint-initdb.d` run only when PostgreSQL
initializes a new data volume. Do **not** run `docker compose down -v` on a
production deployment; that can delete citizen data.

For an existing database, apply the newer query index manually:

```bash
docker compose exec db psql -U sewasetu -d sewasetu -c \
"CREATE INDEX IF NOT EXISTS applications_status_submitted_idx ON applications (status, submitted_at);"
```

If the database password itself must be rotated, change it inside PostgreSQL,
update `SEWA_DB_PASSWORD` in `.env`, and restart the services. The exact
rotation procedure is documented in
[DATA_EXPOSURE_FIX.md](./fixes/DATA_EXPOSURE_FIX.md).

Verify the scheduler after deployment:

```bash
docker compose logs --tail=100 scheduler
docker compose exec scheduler python /app/scripts/deemed_approval.py
```

The command reports how many overdue applications were persisted as deemed
approved. The scheduled job uses Asia/Kolkata time and loads `app.ini`.

## Portal routes

| Purpose | Route |
|---|---|
| Citizen landing page | `/` |
| Start an application | `/apply` |
| Citizen status login | `/status` |
| Application status | `/application/<id>` |
| Edit eligible application | `/application/<id>/edit` |
| Department admin login | `/admin` |
| Admin dashboard | `/admin/dashboard` |
| Admin application list | `/admin/applications` |

Admin credentials are deployment secrets and are not documented in this
repository.

## Verification

Run the focused tests:

```bash
cd app
python3 -m unittest discover -s tests -p 'test_*.py'
```

The current focused suite covers:

- Unicode name preservation and character limits.
- Strict date parsing.
- Age boundary behavior on the application date.
- Existing upload validation behavior.

Additional verification:

```bash
python3 -m py_compile app/app.py app/application_validation.py \
  app/upload_validation.py app/scripts/deemed_approval.py smsgw/app.py
git diff --check
```

## Evidence and presentation

The supplied production logs were used to investigate the incidents:

- The deemed-approval job succeeded through 14 March 2026, then failed because
  it referenced the nonexistent `config/settings.ini`.
- Month-end traffic produced PostgreSQL `too many clients already` errors and
  30-second declaration timeouts.
- A security review identified public SMS history, unauthorized application
  access, unprotected acknowledgment PDFs, SQL injection in password reset,
  and committed credentials.

The complete documentation is organized in [fixes/](./fixes/). For the
three-minute Loom, use [FIXES_SUMMARY.md](./fixes/FIXES_SUMMARY.md), which
covers the problem, evidence, fix, verification, and the deliberate decision
not to redesign the already usable frontend.

## Scope decision

The existing frontend was already straightforward for the citizen journey, so
this submission avoids a visual redesign. Frontend changes were limited to
functional improvements: validation hints, clearer error messages, the edit
application action, and deemed-approval status messaging. The priority was
protecting citizens and keeping the statutory service reliable.

## Operational cautions

- Do not expose PostgreSQL or the SMS gateway port publicly.
- Do not commit `.env`, credentials, production logs, or citizen data.
- Do not delete the `pgdata` volume during deployment.
- Rotate any credentials that were previously present in repository history.
- Use HTTPS, rate limiting, CSRF protection, MFA for staff, and centralized
  audit logging in a production hardening phase.
