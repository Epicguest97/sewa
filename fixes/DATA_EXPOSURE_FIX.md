# Citizen data exposure and account security fix

## Reported concern

Citizens reported receiving sales calls and visits shortly after applying.
The earlier upload fix was not related: it protected the filesystem from
malicious upload filenames and spoofed file types, but it did not control
access to application data or SMS history.

The supplied code contained several confirmed ways for an unauthorized person
to obtain mobile numbers and other personal information:

1. The public `__gateway` proxy republished the internal SMS gateway. Its
   message API contained OTPs, mobile numbers, application numbers, and
   password-reset messages.
2. Acknowledgment PDFs were available at sequential numeric IDs without
   authentication. Each PDF contained a name, mobile number, date of birth,
   address, bank account, and IFSC.
3. A citizen who logged into any status account could request another
   citizen's application by changing the numeric application ID.
4. Password reset interpolated the submitted mobile number into SQL.
5. Password reset immediately replaced a password using the date of birth and
   did not prove control of the registered mobile number.
6. Admin credentials and the Flask session-signing key were stored in source.
7. Admin approve/reject routes accepted any session marked `logged_in`,
   including a citizen portal session.

## Changes

- Disabled the public SMS gateway proxy. The gateway remains internal to the
  Docker network and its inbox is no longer exposed through the portal.
- Restricted acknowledgment PDFs to the authenticated owner or an
  authenticated administrator. Sequential IDs no longer authorize access.
- Added an ownership predicate to the citizen application-status query.
- Parameterized the password-reset queries to remove SQL injection.
- Changed reset to a short-lived verification-code flow. A random temporary
  password is generated only after the code is confirmed and is sent through
  the registered mobile channel. The old DOB-derived password reset is gone.
- Restricted application approval and rejection to `admin` sessions.
- Removed the committed session secret and hardcoded admin credentials from
  the application source. Docker Compose now requires `SEWA_SECRET_KEY`,
  `SEWA_ADMIN_USERNAME`, `SEWA_ADMIN_PASSWORD`, and `SEWA_DB_PASSWORD` from
  an ignored `.env` file. The committed database password was removed too.

## Deployment

Create `.env` on the server from [../.env.example](../.env.example), replace every
placeholder with a strong random value, and keep the file out of Git:

```bash
cp .env.example .env
openssl rand -hex 32
```

Set the generated value as `SEWA_SECRET_KEY`, set unique admin and database
passwords, then rebuild:

```bash
docker compose up -d --build
```

If the PostgreSQL volume already exists, changing `POSTGRES_PASSWORD` in
Compose does not change the password inside PostgreSQL. Rotate the database
credential deliberately before restarting the application:

```bash
docker compose exec -u postgres db psql -d sewasetu \
  -c "ALTER USER sewasetu PASSWORD 'REPLACE_WITH_THE_NEW_VALUE';"
```

Put the same new value in `.env` as `SEWA_DB_PASSWORD`, then rebuild. Keep
the command out of shell history where operational policy requires it.

Rotating `SEWA_SECRET_KEY` invalidates existing Flask sessions, which is
intentional after this exposure. Rotating the admin password is also required
before production use. Do not expose port 8025 publicly; the compose file
keeps the SMS service internal.

## Limitations and follow-up hardening

This fix protects the confirmed application-level paths. Production should
also use HTTPS, rate-limit OTP and reset requests, add CSRF protection to
state-changing forms, use per-user admin accounts with MFA and audit logs,
and monitor access to SMS and document services. SMS providers and staff
accounts should be reviewed for any access outside this application.
