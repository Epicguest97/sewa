# Month-end performance and scheduler reliability fix

## Evidence

The supplied production logs show two separate failures:

- The deemed-approval job succeeded through 14 March 2026, then failed every
  night with `FileNotFoundError: /app/config/settings.ini`. The image contains
  `config/app.ini`, so overdue records stopped being persisted.
- PostgreSQL repeatedly logged `FATAL: sorry, too many clients already`.
  During month-end bursts, `POST /declaration` accounted for the slow requests
  and frequently reached the 30-second Gunicorn timeout. The route opened
  direct database connections per request, generated a PDF synchronously, and
  waited for the SMS gateway before responding.

## Why the site slowed down

The important path is the final declaration submission:

1. A citizen submits `POST /declaration`.
2. The Flask worker opens a new PostgreSQL connection for that request.
3. It checks whether the mobile number already has an application.
4. It inserts the application and checks or creates the status-portal account.
5. It commits the transaction.
6. It generates the acknowledgment PDF in the same web request.
7. It writes the PDF to disk.
8. It calls the SMS gateway synchronously and waits up to five seconds.
9. Only then does the browser receive the confirmation response.

That design makes one web request hold resources for the entire duration of
database work, PDF generation, filesystem I/O, and SMS network I/O. Under
normal traffic this is easy to miss because each request is short enough.
Near the disbursement deadline, many citizens submit at once. The application
then creates more direct PostgreSQL connections than the database is
configured to accept. PostgreSQL rejects new connections with `too many
clients already`.

The rejected requests do not fail quickly in every layer. Other requests are
queued behind busy Gunicorn workers, database connection attempts, or
transactions. A worker handling a declaration cannot serve another request
until its declaration finishes or Gunicorn kills it at the 30-second timeout.
The reverse proxy records those failures as `504` responses at approximately
`rt=30.001`. This explains why the symptom looks like a general site outage
even though the traffic is concentrated on the declaration path.

The logs quantify the pattern: out of 68,664 declaration requests, 22,977
took at least five seconds and 6,873 reached the 30-second timeout. The
repeated `FATAL: sorry, too many clients already` messages confirm that this
was connection exhaustion, not simply a slow internet connection or a
large single database query.

The site appears to recover the next day because the burst ends. Fewer
requests then compete for workers and database connections, so the database
returns below its connection limit. That recovery does not fix the defect;
the same burst recreates it at the next deadline.

The PDF loop amplified the problem. Each acknowledgment drew 2,000 loop
iterations and 4,000 line operations before the response could finish. That
CPU work was repeated by every concurrent declaration request, competing with
the workers' database and application work. The SMS call added a further
per-request network wait.

## Why the scheduler failure was separate

The scheduler failure was not caused by month-end load. Cron continued to
launch the job, but Python exited immediately while importing configuration:
the script requested `/app/config/settings.ini`, a file that is not present
in the image. Because the cron command redirected output to the shared log,
the only visible result was the repeated traceback; no SQL `UPDATE` ran after
the configuration error. The automatic approval rule therefore stopped
persisting status changes even though the application itself remained online.

## Changes

- Use a bounded `ThreadedConnectionPool` per Gunicorn worker. Connections are
  returned to the pool with a rollback after every request, including early
  validation and duplicate paths. The pool is process-aware so workers do not
  share connections across a fork.
- Configure the per-worker pool maximum as `database.pool_max = 8`, preventing
  request bursts from creating unbounded PostgreSQL clients.
- Add an index on `(status, submitted_at)` for the deemed-approval and
  overdue-application queries.
- Replace the acknowledgment PDF's 4,000-iteration decorative border loop with
  one rectangle, removing avoidable CPU work from every declaration submission.
- The scheduler configuration filename was corrected in the deemed-approval
  fix; its repeated `FileNotFoundError` is recorded in
  [DEEMED_APPROVAL_FIX.md](./DEEMED_APPROVAL_FIX.md).

## Why the fixes address the causes

- The connection pool puts a hard ceiling on database clients created by each
  Gunicorn worker. A request can borrow a connection, but it must return it
  after use, so a traffic spike cannot create an unlimited number of database
  sessions.
- The process-aware initialization matters because Gunicorn forks workers.
  A connection pool created before a fork could contain connections shared
  across processes, which is unsafe. Each worker gets its own pool.
- Rolling back before returning a connection clears any failed transaction
  state. Without this, a reused connection could remain in an aborted
  transaction and fail later unrelated requests.
- The `(status, submitted_at)` index lets the deemed-approval job find
  untouched overdue rows without scanning the whole applications table.
- Replacing the border loop removes thousands of repeated drawing operations
  from the synchronous declaration path.

The pool controls database pressure; it does not make unlimited traffic free.
Production should still use request-rate limits, database monitoring, a
connection pool sized against PostgreSQL's `max_connections`, and a separate
background worker for PDF generation and SMS delivery if month-end volume
continues to grow.

## Deployment note

The schema scripts run only when PostgreSQL initializes a new data volume.
For an existing production database, apply the new index manually:

```sql
CREATE INDEX IF NOT EXISTS applications_status_submitted_idx
    ON applications (status, submitted_at);
```

Do not delete the database volume during deployment.
