# Sewa Setu fixes — three-minute Loom summary

## Opening: what this portal does

Sewa Setu is the Old Age Pension application portal. Citizens verify a mobile
number, complete the form, upload age proof, submit an application, and track
the result. The main risks were citizen data exposure, incorrect statutory
processing, poor form usability, and instability during month-end traffic.

## Fix 1 — Secure document uploads

The upload endpoint previously trusted filenames and had inconsistent size and
format handling. A crafted filename could influence the storage path.

The fix validates JPG/JPEG/PDF signatures, enforces the 5 MB limit, sanitizes
the submitted filename, and stores files using a server-generated name. This
prevents path traversal and extension spoofing. The upload fix does not itself
control who can download a document, so document authorization was fixed
separately.

See [UPLOAD_SECURITY_FIX.md](./UPLOAD_SECURITY_FIX.md).

## Fix 2 — Correct names, dates, age, and duplicate applications

Unicode names were truncated by UTF-8 byte count and could appear as question
marks. Names now use Unicode normalization and character-based limits.
Acknowledgment PDFs use a Unicode font.

Dates now require `DD/MM/YYYY`, such as `06/06/1960`, rather than ambiguous
formats or `06061960`. Age is calculated on the actual application date:
exactly 60 years old is eligible. A database uniqueness constraint prevents
two applications for the same verified mobile number, including concurrent
submissions.

See [APPLICATION_VALIDATION_FIX.md](./APPLICATION_VALIDATION_FIX.md).

## Fix 3 — IST deadline and deemed approval

The application window now closes at midnight India Standard Time. Untouched
applications become eligible for deemed approval after 15 complete days.

The citizen status page immediately shows an overdue pending file as approved,
even before the scheduled job runs. The scheduler persists `DEEMED_APPROVED`
and sends the citizen an SMS.

The production logs showed the scheduler had stopped because it referenced
`/app/config/settings.ini`, while the deployed file is `app.ini`. That path
was corrected.

See [DEEMED_APPROVAL_FIX.md](./DEEMED_APPROVAL_FIX.md).

## Fix 4 — Citizen editing

Citizens can now edit a submitted application from the authenticated status
portal while it is still pending and within the 15-day processing period.
Approved, rejected, deemed-approved, and overdue applications cannot be edited.

The update checks the authenticated owner, current status, and deadline
atomically, so a stale edit form cannot overwrite an administrative decision.
All relevant validation is repeated on the server.

See [EDIT_APPLICATION_FIX.md](./EDIT_APPLICATION_FIX.md).

## Fix 5 — Month-end performance and scheduler reliability

Production logs showed 68,664 declaration requests, 22,977 taking at least
five seconds, and 6,873 reaching the 30-second timeout. PostgreSQL reported
`too many clients already`.

The cause was unbounded database connections per request combined with
synchronous PDF generation, filesystem work, and SMS network waiting. The
system slowed during the deadline burst and recovered only when traffic fell.

The fix adds a bounded per-worker PostgreSQL connection pool, safely returns
connections, adds an index for overdue-file queries, and replaces a 4,000-step
PDF border loop with one rectangle.

See [PERFORMANCE_FIX.md](./PERFORMANCE_FIX.md).

## Fix 6 — Citizen data exposure and account security

The security review found that the upload fix was not enough. The public SMS
gateway proxy exposed OTPs and message history. Sequential acknowledgment PDF
IDs exposed personal and bank data. Logged-in citizens could access other
citizens' records by changing an application ID. Password reset used
SQL-injected input and predictable DOB passwords. Admin credentials and the
Flask session secret were committed to source.

The fixes disable the public SMS proxy, enforce application ownership on
status and PDF routes, parameterize password-reset queries, require a
short-lived SMS verification code, generate a random temporary password,
require admin authorization for decisions, and move secrets into the ignored
EC2 `.env` file.

See [DATA_EXPOSURE_FIX.md](./DATA_EXPOSURE_FIX.md).

## Closing: evidence and deployment

The focused regression suite passes, changed Python modules compile, and
editor diagnostics are clean. The important deployment detail is to create
the server `.env` before rebuilding and never run `docker compose down -v`,
because that can delete the PostgreSQL citizen-data volume.

The strongest evidence-driven findings were:

- deemed approvals stopped after the configuration filename mismatch;
- month-end slowness came from database connection exhaustion;
- the reported sales-call rumor was consistent with exposed SMS history and
  other unauthorized data-access paths, not with the upload filename fix.

## What I chose not to change

I did not redesign the frontend or add visual features. The existing interface
is already straightforward and usable for the citizen journey, so a visual
redesign would have had lower citizen impact than fixing data exposure,
incorrect approval processing, application-edit limitations, validation
errors, and month-end reliability. I made only targeted frontend changes where
they were necessary to support those fixes, such as clearer validation
messages, date-format hints, the edit-application action, and the approved
status explanation.
