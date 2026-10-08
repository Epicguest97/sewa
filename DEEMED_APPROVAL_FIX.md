# Deadline and deemed-approval fix

## Problems

The application deadline was evaluated with the server's local clock, so a
deployment running in UTC could close the portal at the wrong time. The
deemed-approval job also loaded a configuration filename that is not shipped
with the application. Finally, a citizen could see `PENDING` until the
nightly job happened to update the row, even though the statutory 15-day
period had already elapsed.

## Changes

- Interpret the configured final scheme date in Asia/Kolkata and close the
  application window at 00:00 IST on the following day.
- Store new application receipt timestamps as India-local naive timestamps,
  matching the existing PostgreSQL `timestamp` columns.
- Run deemed-approval cutoffs in Asia/Kolkata and include applications whose
  15-day deadline has exactly elapsed.
- Fix the scheduled job to load the shipped `app.ini`.
- Project overdue untouched `PENDING` applications as `DEEMED_APPROVED` in
  the citizen status page immediately. The nightly job still persists the
  status and sends the statutory notification.
- Display projected or persisted deemed approval to citizens as `APPROVED`,
  with the RTPS Act basis shown explicitly.

## Verification

The status projection uses the same 15-day cutoff as the scheduled job, so
the citizen-facing result does not depend on cron timing. Existing rows are
not changed by this fix; the scheduled job updates only untouched `PENDING`
rows that have crossed the deadline.

## Operational incident evidence

The supplied production `cron.log` shows successful runs through 14 March
2026, followed by repeated `FileNotFoundError` failures for
`/app/config/settings.ini`. The deployed application ships
`/app/config/app.ini`, so no applications were persisted as deemed-approved
after the configuration mismatch.
