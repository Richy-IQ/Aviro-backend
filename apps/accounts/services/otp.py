"""
Issuing and delivering verification codes.

Kept out of the views so the rules — how often a code may be requested, how
many attempts a code allows, what happens on success — are readable in one
place and testable without HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import DomainError

from ..models import OtpCode, User

logger = logging.getLogger(__name__)

# A farmer who taps "resend" immediately should be told to wait rather than
# costing another message.
RESEND_INTERVAL = timedelta(seconds=30)


class OtpThrottled(DomainError):
    default_detail = "A code was just sent. Wait a moment before asking for another."
    default_code = "otp_throttled"


@dataclass(frozen=True)
class VerifyResult:
    """
    The outcome of checking a code.

    Returned rather than raised: a wrong code is an ordinary thing for a farmer
    to do, not an exceptional one. It also matters mechanically — DRF rolls the
    request transaction back on any APIException, which would undo the record
    of the failed attempt and leave the six-digit code brute-forceable.
    """

    ok: bool
    user: User | None = None
    created: bool = False
    code: str = ""
    message: str = ""

    @classmethod
    def failure(cls, code: str, message: str) -> VerifyResult:
        return cls(ok=False, code=code, message=message)


def request_code(phone_e164: str) -> tuple[OtpCode, str]:
    """
    Issue a code for this number and hand it to the delivery channel.

    Returns the plaintext alongside the record so the caller can echo it in
    demo mode. It is never stored and never logged outside console delivery.
    """
    recent = OtpCode.objects.filter(phone=phone_e164).first()
    if recent and timezone.now() - recent.created_at < RESEND_INTERVAL:
        raise OtpThrottled()

    otp, plaintext = OtpCode.issue(phone_e164)
    _deliver(phone_e164, plaintext)
    return otp, plaintext


def verify_code(phone_e164: str, submitted: str) -> VerifyResult:
    """
    Check a code, creating the account on the first successful verification.

    `created` lets the client send a first-time farmer to "start your first
    batch" and a returning one home.
    """
    otp = OtpCode.objects.filter(phone=phone_e164, consumed_at__isnull=True).first()
    if otp is None:
        return VerifyResult.failure("otp_invalid", "That code is not correct. Ask for a new one.")
    if otp.is_expired:
        return VerifyResult.failure("otp_expired", "That code has expired. Ask for a new one.")
    if not otp.is_usable:
        return VerifyResult.failure(
            "otp_invalid", "Too many attempts on that code. Ask for a new one."
        )
    if not otp.verify(submitted):
        return VerifyResult.failure(
            "otp_invalid", "That code is not correct. Check it and try again."
        )

    user, created = User.objects.get_or_create(phone=phone_e164)
    if not user.is_active:
        return VerifyResult.failure("account_disabled", "This account has been disabled.")
    user.mark_phone_verified()
    return VerifyResult(ok=True, user=user, created=created)


def _deliver(phone_e164: str, code: str) -> None:
    """
    Send the code.

    Development prints it, so no message is spent and no provider is needed to
    work on the app. Production sends over WhatsApp where possible and falls
    back to SMS: WhatsApp is more reliable and cheaper than Nigerian SMS, and
    nearly every farmer already has it.

    The SMS body must end with "@<domain> #<code>" for the browser's Web OTP
    API to autofill it on Android — the frontend depends on that exact shape.
    """
    channel = getattr(settings, "OTP_DELIVERY", "console")

    if channel == "console":
        # Printed prominently rather than as a plain log line: while no
        # provider is configured this is the only way to sign in, and a single
        # INFO line is easy to lose among request logs.
        logger.info(
            "\n"
            "  ===============================================\n"
            "   AVIRO SIGN-IN CODE\n"
            "   %s  ->  %s\n"
            "   No SMS provider configured, so it is printed here.\n"
            "   Set OTP_DELIVERY to change that.\n"
            "  ===============================================",
            phone_e164,
            code,
        )
        return

    # Deliberately not implemented: wiring a provider means credentials and a
    # billing account, which is a deployment decision rather than a code one.
    raise NotImplementedError(
        f"OTP_DELIVERY={channel!r} has no provider configured. "
        "Implement _deliver() against your WhatsApp Business or SMS gateway."
    )
