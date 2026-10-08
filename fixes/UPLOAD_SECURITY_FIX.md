# Upload validation and security fix

## Why this matters

Citizens upload age-proof documents that may contain names, dates of birth,
addresses, and identity information. An upload endpoint must therefore protect
both the application server and the citizen's document. File extensions and
browser restrictions are not security controls: an attacker can send a
hand-crafted HTTP request with any filename and any bytes.

## Problem

The upload page promised JPG or PDF documents up to 5 MB, but the backend only
accepted filenames ending in `.pdf` and rejected files larger than 100 KB. It
also displayed the internal `ERR_VAL_47` code to citizens. The backend trusted
the filename extension and reused the submitted filename in the storage path.
This created both a usability defect and security risks:

1. A legitimate JPG could not be uploaded even though the page promised JPG.
2. The real limit was 100 KB rather than the documented 5 MB.
3. A filename containing path components could influence where the file was
   written. This is a path traversal risk and could overwrite an unintended
   file if the process had permission.
4. A file could be given a harmless-looking extension while containing
   unrelated or dangerous bytes.
5. Repeated large uploads could consume memory or disk space.

## Changes

- Accept `.jpg`, `.jpeg`, and `.pdf` documents.
- Enforce the documented 5 MB maximum (`5 * 1024 * 1024` bytes).
- Validate file signatures:
  - PDF files must begin with `%PDF-`.
  - JPG/JPEG files must begin with the JPEG marker `FF D8 FF`.
- Sanitize the submitted filename before inspecting it.
- Store each accepted document under a server-generated UUID filename. The
  submitted filename can no longer influence the storage path.
- Replace `ERR_VAL_47` with clear, citizen-facing validation messages.
- Add an `accept` hint and required field to the upload form.
- Add unit tests covering successful PDF/JPEG uploads, spoofed extensions,
  unsupported formats, and the size limit.

## Security behavior

### Path traversal and unsafe filenames

The submitted filename is used only to determine the requested extension after
removing path components. It is not used as the saved filename. The server
creates a new name from the verified mobile number, a random UUID, and the
validated extension. For example, a submitted name such as
`../../app.py` cannot cause the application to write to `app.py`.

This prevents the original filename from selecting an arbitrary filesystem
path. The upload directory must still be configured outside the application
source tree and must not allow uploaded files to execute as server-side code.

### Extension spoofing and file signatures

The browser's `accept` attribute is only a user-interface hint and can be
ignored. The server therefore checks both the extension and the initial file
signature:

- PDFs must start with `%PDF-`.
- JPEG files must start with the JPEG marker `FF D8 FF`.

This blocks a text file renamed to `document.pdf` or an unrelated file renamed
to `photo.jpg`. A signature check is not a complete malware scan and does not
prove that the document is a genuine certificate.

### Size and denial of service

The server reads at most 5 MB plus one byte. The extra byte lets it distinguish
a file exactly at the limit from a file that exceeds it without reading an
unbounded upload into memory. This reduces the risk from oversized individual
uploads, but it does not replace request rate limiting, connection limits, or
disk quotas. Those controls should be configured at the reverse proxy and
deployment level.

### Citizen data protection

Age-proof documents are sensitive personal data. Random storage names make
guessing paths harder, but random names are not authorization. Any future
download or preview endpoint must check that the requester is authorized to
access the specific application. Directory listing must be disabled, and
documents should be served through an access-controlled endpoint rather than
as public static files.

## Scope and limitations

This fix accepts the formats promised by the existing user interface: JPG,
JPEG, and PDF. It verifies format signatures and size, but it does not:

- scan files for malware;
- fully parse or sanitize PDF and image structures;
- prove that an uploaded document is authentic;
- provide request rate limiting or a total storage quota;
- add CSRF protection to the complete application flow; or
- replace authorization on future document retrieval endpoints.

These are follow-up production hardening items. If an approved malware scanner
is available, files should be quarantined and scanned before being made
available to staff. The upload directory should be non-executable, outside
the web root, and protected by filesystem permissions.

## Verification

The focused test suite covers:

- valid JPG acceptance;
- valid PDF acceptance;
- rejection of extension spoofing;
- rejection of unsupported formats; and
- rejection of files over 5 MB.

The changed Python files compile successfully, and the focused suite passes
with four tests.

## Data preservation

The original upload contents are preserved. Only the generated storage name
changes, and no citizen records are deleted or altered.
