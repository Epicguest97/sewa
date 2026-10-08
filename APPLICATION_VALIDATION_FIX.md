# Application validation fix

## Problems

The personal-details form had three citizen-impacting defects:

- Applicant names were truncated by UTF-8 byte length. This could cut a
  multi-byte character in half, and the acknowledgment PDF used a font that
  could render non-Latin names as `?`.
- The server accepted ambiguous month/day parsing and did not accept the
  documented format consistently. Citizens need to enter `06/06/1960`, not
  `06061960`.
- Age validation was only performed at final submission and did not clearly
  state the rule that the applicant must be at least 60 on the application
  date. Duplicate checks were application-level only, so concurrent requests
  could race.

## Changes

- Normalize names to Unicode NFC and limit them to 100 characters rather than
  100 UTF-8 bytes. The value is retained as Unicode for PostgreSQL and HTML
  output.
- Install and use DejaVu Unicode fonts for generated acknowledgments.
- Require and validate `DD/MM/YYYY` on the form and server. Compact or
  ambiguous formats are rejected with a citizen-facing message.
- Reject future birth dates and calculate age using the applicant's birthday
  relative to the date of application. Exactly 60 years old is eligible.
- Add a database unique index on the verified mobile number, while retaining
  the existing friendly duplicate message and handling a concurrent insert
  safely.

## Verification

`app/tests/test_application_validation.py` covers Unicode preservation,
character-based limits, strict date parsing, and the birthday boundary for
age eligibility. The application form also uses required fields, a date
pattern, and numeric input hints for immediate browser feedback. The pure
validation helpers are kept in `app/application_validation.py`, so these
regressions can run without connecting to PostgreSQL.

Existing application rows are not changed or deleted. The uniqueness index
assumes the supplied production data's verified mobile numbers are unique;
the duplicate check was verified against the supplied seed data before adding
the constraint.
