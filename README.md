# Sewa Setu

## Old Age Pension Application Portal

Sewa Setu is a Flask and PostgreSQL web application for managing applications
for the Old Age Pension Scheme. It supports the complete application journey:
mobile verification, multilingual citizen data, document upload, application
tracking, controlled corrections, and departmental review.

This repository contains an internship submission focused on **correctness,
security, statutory compliance, and operational reliability**. The changes
were made against the existing application and are documented with the
evidence, root cause, implementation, and verification for each issue.

## Submission highlights

| Area | Implemented improvement |
| --- | --- |
| Citizen data | Unicode-safe names and multilingual PDF output |
| Eligibility | Strict `DD/MM/YYYY` date handling and age validation on the application date |
| Duplicate prevention | Database-enforced one-application-per-mobile rule |
| Statutory processing | IST application cutoff and 15-day deemed approval |
| Citizen corrections | Secure editing of eligible pending applications |
| File security | File type, signature, size, filename, and storage validation |
| Access control | Citizen ownership checks, protected PDFs, and admin-only decisions |
| Account security | SMS-verified password reset and environment-managed credentials |
| Performance | Bounded database pooling, query indexing, and lighter PDF generation |
| Deployment | Docker Compose topology with private application services and Nginx |

## Key functional rules

- Names are normalized without corrupting non-ASCII characters.
- Date of birth must use `DD/MM/YYYY`, for example `06/06/1960`.
- The applicant must be at least 60 years old on the India Standard Time date
  of application.
- A verified mobile number can have only one application, including during
  concurrent submissions.
- The application window closes at midnight Asia/Kolkata time after the
  configured final application day.
- An untouched pending application is deemed approved at the 15-day statutory
  cutoff. Citizens see the approved status immediately; the scheduled job
  persists the status in the database.
- Applicants may edit pending applications during the permitted processing
  window. Approved, rejected, and deemed-approved applications cannot be
  edited.

## Technical architecture

```text
Citizen browser
      |
      v
Nginx reverse proxy :80/:443
      |
      v
Flask application :8000 (private Docker network)
      |                 \
      v                  v
PostgreSQL :5432      Internal SMS gateway :8025
      ^
      |
Deemed-approval scheduler
```

The application, PostgreSQL database, scheduler, and SMS gateway run as
separate Docker Compose services. Only Nginx is intended to be internet-facing.
The application, database, and SMS gateway ports are not published publicly.
Certificate files and the ACME webroot use persistent named volumes.

## Repository structure

```text
app/
  app.py                         Flask routes and application services
  application_validation.py      Shared Unicode, date, and age validation
  upload_validation.py           Upload type, signature, and size validation
  schema.sql                     PostgreSQL schema and indexes
  scripts/deemed_approval.py     Statutory approval scheduler
  templates/                     Citizen and department views
  tests/                         Focused regression tests
smsgw/                            Internal simulated SMS gateway
seed/                             Database seed data
fixes/                            Issue documentation and presentation summary
nginx/                            HTTP and TLS reverse-proxy configurations
docker-compose.yml                Local and EC2 service topology
.env.example                      Deployment secret template
```

## Run locally

### Requirements

- Docker Engine
- Docker Compose v2

Create a local environment file:

```bash
cp .env.example .env
```

Replace the placeholder values in `.env` with development-only secrets. Do
not commit `.env`.

Start the services:

```bash
docker compose up -d --build
docker compose ps
```

The portal is available at:

```text
http://localhost:8000
```

The SMS gateway is reachable only by the application over the private Docker
network. Its simulated messages are held in memory and are cleared when the
gateway container restarts.

## Production deployment

On the deployment host:

```bash
git pull origin master
cp .env.example .env       # first deployment only
nano .env
docker compose up -d --build
docker compose ps
```

Required environment variables:

```env
SEWA_SECRET_KEY=<long-random-Flask-session-secret>
SEWA_ADMIN_USERNAME=<department-admin-username>
SEWA_ADMIN_PASSWORD=<long-random-admin-password>
SEWA_DB_PASSWORD=<PostgreSQL-password>
```

For `sewa.mehul.sbs`, configure the DNS `A` record to the EC2 Elastic IP and
allow inbound TCP ports 80 and 443 in the EC2 security group. Use the Nginx
configurations in [nginx/](./nginx/) for the ACME challenge and TLS
termination. Do not expose ports 8000, 5432, or 8025.

### Protecting existing data

PostgreSQL initialization scripts run only when a new database volume is
created. Never use `docker compose down -v` on a deployment containing
citizen data.

For an existing database, apply the performance index explicitly:

```bash
docker compose exec db psql -U sewasetu -d sewasetu -c \
"CREATE INDEX IF NOT EXISTS applications_status_submitted_idx ON applications (status, submitted_at);"
```

Check the scheduler after deployment:

```bash
docker compose logs --tail=100 scheduler
docker compose exec scheduler python /app/scripts/deemed_approval.py
```

The scheduler uses Asia/Kolkata time and reads `app.ini`. Credentials that
were previously present in repository history should be rotated before
production use.

## Important routes

| Purpose | Route |
| --- | --- |
| Citizen landing page | `/` |
| Start an application | `/apply` |
| Citizen status login | `/status` |
| Application status | `/application/<id>` |
| Edit an eligible application | `/application/<id>/edit` |
| Department login | `/admin` |
| Department dashboard | `/admin/dashboard` |
| Department application list | `/admin/applications` |

## Verification

Run the focused regression suite:

```bash
cd app
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run syntax and whitespace checks from the project root:

```bash
python3 -m py_compile app/app.py app/application_validation.py \
  app/upload_validation.py app/scripts/deemed_approval.py smsgw/app.py
git diff --check
```

The tests cover Unicode name handling, strict date parsing, age-boundary
behavior, and upload validation. The issue-specific documentation also records
the production log evidence and verification for performance, scheduler, and
security changes.

## Documentation and evidence

The [fixes/](./fixes/) directory contains the detailed engineering record:

- [APPLICATION_VALIDATION_FIX.md](./fixes/APPLICATION_VALIDATION_FIX.md)
- [DEEMED_APPROVAL_FIX.md](./fixes/DEEMED_APPROVAL_FIX.md)
- [EDIT_APPLICATION_FIX.md](./fixes/EDIT_APPLICATION_FIX.md)
- [PERFORMANCE_FIX.md](./fixes/PERFORMANCE_FIX.md)
- [DATA_EXPOSURE_FIX.md](./fixes/DATA_EXPOSURE_FIX.md)
- [UPLOAD_SECURITY_FIX.md](./fixes/UPLOAD_SECURITY_FIX.md)
- [FIXES_SUMMARY.md](./fixes/FIXES_SUMMARY.md)

The supplied production logs showed two principal operational failures:

1. The deemed-approval scheduler referenced `config/settings.ini`, while the
   deployed file was `config/app.ini`. This stopped overdue applications from
   being processed.
2. Peak declaration traffic exhausted PostgreSQL connections and produced
   30-second timeouts. The declaration path also performed database work, PDF
   generation, filesystem operations, and synchronous SMS delivery in one
   request.

These root causes, the resulting changes, and the trade-offs are explained in
[PERFORMANCE_FIX.md](./fixes/PERFORMANCE_FIX.md) and
[DEEMED_APPROVAL_FIX.md](./fixes/DEEMED_APPROVAL_FIX.md).

## Scope and design decision

No visual redesign was introduced because the existing citizen interface was
already usable for the intended workflow. Frontend changes were limited to
functional improvements: validation guidance, clearer error handling, the
application edit action, and deemed-approval status messaging. Development
effort was concentrated on data integrity, security, statutory behavior, and
reliability.

## Production security notes

- Keep `.env`, credentials, logs, and citizen data outside version control.
- Restrict database and SMS gateway access to the private Docker network.
- Use HTTPS for public traffic.
- Consider rate limiting, CSRF protection, MFA for department users, and
  centralized audit logging as further production hardening.
