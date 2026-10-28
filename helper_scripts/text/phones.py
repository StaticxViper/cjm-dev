"""US phone checks shared by lead scripts."""

from __future__ import annotations

import re

US_PHONE_RE = re.compile(
    r"^(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$"
)


def is_valid_us_phone(phone):
    """Return True if phone is present and matches a valid US format."""
    if not phone or not str(phone).strip():
        return False
    phone = str(phone).strip()
    if US_PHONE_RE.match(phone):
        return True
    digits = re.sub(r"[^0-9]", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) == 10
