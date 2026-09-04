"""
Nigerian mobile numbers.

Deliberately mirrors the frontend's lib/phone.ts: people write their number as
08034129087, 8034129087 or +2348034129087, and rejecting any of those is the
API's problem rather than the farmer's. Stored canonically in E.164 so there is
exactly one representation in the database.
"""

from __future__ import annotations

import re

MOBILE_PREFIX = re.compile(r"^[789]")
NATIONAL_LENGTH = 10
COUNTRY_CODE = "234"


class InvalidPhoneNumber(ValueError):
    """The input cannot be a Nigerian mobile number."""


def normalise(raw: str) -> str:
    """
    Reduce any accepted form to the 10 national digits.

    Raises InvalidPhoneNumber rather than returning None, so a caller cannot
    forget to check.
    """
    digits = re.sub(r"\D", "", raw or "")

    if digits.startswith(COUNTRY_CODE):
        national = digits[len(COUNTRY_CODE) :]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits

    if len(national) != NATIONAL_LENGTH or not MOBILE_PREFIX.match(national):
        raise InvalidPhoneNumber(f"{raw!r} is not a Nigerian mobile number")
    return national


def to_e164(raw: str) -> str:
    """Canonical storage and delivery form: +2348034129087."""
    return f"+{COUNTRY_CODE}{normalise(raw)}"


def mask(e164: str) -> str:
    """For 'we sent a code to…' messages, without repeating the whole number."""
    return f"+234 ••• ••• {e164[-4:]}"
