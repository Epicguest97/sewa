import io
import unittest

from upload_validation import validate_uploaded_document


class FakeUpload:
    def __init__(self, filename, content):
        self.filename = filename
        self.stream = io.BytesIO(content)

    def read(self, size):
        return self.stream.read(size)


class UploadValidationTests(unittest.TestCase):
    def make_upload(self, filename, content):
        return FakeUpload(filename, content)

    def test_accepts_jpeg_with_jpeg_signature(self):
        content, extension, error = validate_uploaded_document(
            self.make_upload("age-proof.JPG", b"\xff\xd8\xff" + b"image data")
        )
        self.assertEqual(content, b"\xff\xd8\xffimage data")
        self.assertEqual(extension, ".jpg")
        self.assertIsNone(error)

    def test_accepts_pdf_with_pdf_signature(self):
        content, extension, error = validate_uploaded_document(
            self.make_upload("certificate.pdf", b"%PDF-1.7\ncontent")
        )
        self.assertEqual(content, b"%PDF-1.7\ncontent")
        self.assertEqual(extension, ".pdf")
        self.assertIsNone(error)

    def test_rejects_extension_spoofing(self):
        content, extension, error = validate_uploaded_document(
            self.make_upload("not-a-pdf.pdf", b"not a PDF")
        )
        self.assertIsNone(content)
        self.assertIsNone(extension)
        self.assertIn("valid", error)

    def test_rejects_unsupported_files_and_oversized_files(self):
        _, _, error = validate_uploaded_document(
            self.make_upload("age-proof.png", b"\x89PNG\r\n")
        )
        self.assertIn("JPG, JPEG, or PDF", error)

        _, _, error = validate_uploaded_document(
            self.make_upload("large.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024))
        )
        self.assertIn("5 MB", error)


if __name__ == "__main__":
    unittest.main()
