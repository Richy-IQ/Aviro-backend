"""
Payment providers.

Two, behind one small interface. Paystack is the real one: the standard in
Nigeria, and it takes card, bank transfer and USSD, which matters because many
farmers do not have a card. The fake one settles instantly so the whole flow can
be walked locally without moving money; production refuses to start with it.

Paystack is called with the standard library rather than a new dependency. Two
endpoints do not justify one, and a payment path benefits from having nothing in
it that is not needed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class ProviderUnavailable(APIException):
    """
    The payment provider could not be reached, or refused the request.

    The farmer is shown a plain sentence. What the provider actually said —
    "Invalid key", "Invalid Email Address Passed" — is kept on the exception,
    logged, and recorded on the payment, because it is the whole diagnosis and
    is no use to a farmer.
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Payments are not available just now. Please try again shortly."
    default_code = "payment_provider_unavailable"

    def __init__(self, detail=None, *, provider_message: str = ""):
        super().__init__(detail)
        self.provider_message = provider_message


def clean_key(raw: str) -> str:
    """
    A secret key as pasted into a dashboard, made usable.

    Stray whitespace or a trailing newline makes Python refuse to send the
    header at all, and surrounding quotes are sometimes pasted in with the
    value. A real key contains neither.
    """
    return raw.strip().strip("'\"").strip()


@dataclass(frozen=True)
class Checkout:
    authorization_url: str
    reference: str


@dataclass(frozen=True)
class Verification:
    # "success", "failed", "abandoned", or anything else the provider says.
    status: str
    amount_kobo: int | None
    currency: str | None
    raw: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def failed(self) -> bool:
        return self.status in {"failed", "reversed"}


class PaystackProvider:
    name = "paystack"
    base_url = "https://api.paystack.co"

    def __init__(self, secret_key: str):
        key = clean_key(secret_key)
        if not key:
            raise ProviderUnavailable(
                "Payments are not configured on this server.",
                provider_message="PAYSTACK_SECRET_KEY is not set",
            )
        self.secret_key = key

    def initialize(
        self, *, email: str, amount_kobo: int, reference: str, callback_url: str, metadata: dict
    ) -> Checkout:
        data = self._call(
            "POST",
            "/transaction/initialize",
            {
                "email": email,
                "amount": amount_kobo,
                "currency": "NGN",
                "reference": reference,
                "callback_url": callback_url,
                # Bank transfer and USSD alongside card: plenty of farmers have
                # a bank account and a phone, and no card.
                "channels": ["card", "bank", "ussd", "bank_transfer"],
                "metadata": metadata,
            },
        )
        return Checkout(authorization_url=data["authorization_url"], reference=data["reference"])

    def verify(self, reference: str) -> Verification:
        data = self._call("GET", f"/transaction/verify/{urllib.parse.quote(reference)}")
        return Verification(
            status=str(data.get("status", "")),
            amount_kobo=data.get("amount"),
            currency=data.get("currency"),
            raw=data,
        )

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            # Paystack refuses a request with a 4xx and a JSON body saying why.
            # HTTPError is a URLError, so it must be caught first or the reason
            # is lost with it.
            reason = _reason_from(exc)
            logger.warning("Paystack %s %s refused (%s): %s", method, path, exc.code, reason)
            raise ProviderUnavailable(provider_message=f"HTTP {exc.code}: {reason}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("Paystack %s %s could not be reached: %r", method, path, exc)
            raise ProviderUnavailable(provider_message=f"Unreachable: {exc!r}") from exc

        if not payload.get("status"):
            reason = payload.get("message") or "no reason given"
            logger.warning("Paystack %s %s declined: %s", method, path, reason)
            raise ProviderUnavailable(provider_message=reason)
        return payload.get("data") or {}


def _reason_from(error: urllib.error.HTTPError) -> str:
    try:
        return json.loads(error.read()).get("message") or error.reason
    except (ValueError, AttributeError, OSError):
        return str(error.reason)


class FakeProvider:
    """
    Settles every payment the moment it is started. Local development only.

    Remembers what each checkout was for, so confirmation still exercises the
    amount check rather than waving everything through.
    """

    name = "fake"

    def initialize(
        self, *, email: str, amount_kobo: int, reference: str, callback_url: str, metadata: dict
    ) -> Checkout:
        cache.set(f"fake-payment:{reference}", {"amount": amount_kobo, "currency": "NGN"}, 3600)
        query = urllib.parse.urlencode({"reference": reference})
        return Checkout(authorization_url=f"{callback_url}?{query}", reference=reference)

    def verify(self, reference: str) -> Verification:
        stored = cache.get(f"fake-payment:{reference}")
        if stored is None:
            return Verification(status="abandoned", amount_kobo=None, currency=None)
        return Verification(
            status="success",
            amount_kobo=stored["amount"],
            currency=stored["currency"],
            raw={"fake": True},
        )


def get_provider():
    if settings.PAYMENTS_PROVIDER == "fake":
        return FakeProvider()
    return PaystackProvider(settings.PAYSTACK_SECRET_KEY)


def signature_is_valid(body: bytes, signature: str | None) -> bool:
    """
    Paystack signs each webhook with HMAC-SHA512 of the raw body.

    Compared in constant time. Without this check anyone could post "charge
    succeeded" and unlock a farm for free.
    """
    key = clean_key(settings.PAYSTACK_SECRET_KEY)
    if not signature or not key:
        return False
    expected = hmac.new(key.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
