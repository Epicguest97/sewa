import unicodedata
from datetime import datetime


def sanitize(value, maxlen=20):
    # Limit Unicode characters, not UTF-8 bytes, so names are not truncated
    # halfway through a character.
    if value is None:
        return ""
    value = unicodedata.normalize("NFC", value.strip())
    return value[:maxlen]


def parse_dob(value):
    """Parse the citizen-facing date format without accepting ambiguous input."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def age_on_date(dob, on_date):
    return on_date.year - dob.year - (
        (on_date.month, on_date.day) < (dob.month, dob.day)
    )
