import unittest
from datetime import date

from application_validation import age_on_date, parse_dob, sanitize


class ApplicationValidationTests(unittest.TestCase):
    def test_sanitize_preserves_unicode_characters(self):
        name = "শ্রীমতী লক্ষ্মী দাস"
        self.assertEqual(sanitize(name, maxlen=100), name)

    def test_sanitize_limits_characters_not_utf8_bytes(self):
        name = "अ" * 100
        self.assertEqual(len(sanitize(name, maxlen=20)), 20)

    def test_parse_dob_requires_dd_mm_yyyy(self):
        self.assertEqual(parse_dob("06/06/1960"), date(1960, 6, 6))
        self.assertIsNone(parse_dob("06061960"))
        self.assertIsNone(parse_dob("1960-06-06"))
        self.assertIsNone(parse_dob(None))

    def test_age_is_calculated_on_application_date(self):
        dob = date(1960, 6, 7)
        self.assertEqual(age_on_date(dob, date(2020, 6, 6)), 59)
        self.assertEqual(age_on_date(dob, date(2020, 6, 7)), 60)


if __name__ == "__main__":
    unittest.main()
