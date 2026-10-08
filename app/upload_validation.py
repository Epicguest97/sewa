import os


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".pdf"}


def validate_uploaded_document(upload):
    """Return validated document bytes and extension, or a user-facing error."""
    submitted_name = os.path.basename(upload.filename or "").strip()
    extension = os.path.splitext(submitted_name)[1].lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, None, "Please upload a JPG, JPEG, or PDF file."

    content = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return None, None, "The document must be 5 MB or smaller."

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        return None, None, "The selected PDF file is not valid."
    if extension in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        return None, None, "The selected image file is not a valid JPG."

    return content, extension, None
