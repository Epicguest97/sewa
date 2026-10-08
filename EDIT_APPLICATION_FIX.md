# Citizen application editing fix

## Problem

After submitting an application, citizens could only view its status. A small
mistake required a help-desk request, manual deletion, and a second
submission. That process was slow and risked duplicate or inconsistent
records.

## Changes

- Added an **Edit application** action to the authenticated citizen status
  page.
- Citizens can correct personal details, date of birth, gender, marital
  details, address, and bank information.
- Editing is allowed only when the application is still `PENDING` and fewer
  than 15 days have elapsed since submission.
- Applications that are approved, rejected, deemed-approved, or exactly at
  the 15-day boundary cannot be edited.
- The edit route requires the status-portal session and verifies that the
  application belongs to the logged-in mobile number.
- The server repeats the Unicode, date-format, age, required-field, and
  widowed-applicant validations; browser validation is not trusted.
- The database update is atomic and checks the status, owner, and deadline in
  the `WHERE` clause. If an administrator decides the application while an
  edit form is open, the edit is rejected rather than overwriting the
  decision.

Uploaded documents are not changed by this flow. If the age-proof document is
wrong, the citizen should contact the department rather than silently
replacing evidence after submission.

## Verification

The existing validation tests continue to cover Unicode names, strict dates,
and age boundaries. The edit path uses those same helpers and performs its
own server-side validation before the atomic update.
