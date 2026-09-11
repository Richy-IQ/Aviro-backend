"""
Taking a payment, from the button to the unlocked statement.

Two rules shape everything here. Never take money for nothing: a farm already
covered for the days a payment would buy is told so and not charged. And never
unlock on the provider's say-so alone: the amount and currency it reports are
checked against what was asked for, so a tampered checkout cannot buy a batch
for one naira.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.farms.models import Farm
from apps.flocks.models import Batch

from ..models import Payment
from . import access
from .providers import FakeProvider, PaystackProvider, ProviderUnavailable, get_provider

logger = logging.getLogger(__name__)

MONTH_DAYS = 30


@dataclass(frozen=True)
class Offer:
    """What paying now would buy, before anyone presses the button."""

    kind: str
    amount: Decimal
    covers_from: date
    covers_until: date
    description: str


@dataclass(frozen=True)
class Started:
    payment: Payment
    authorization_url: str


def _is_monthly(batch: Batch) -> bool:
    # Layers earn every week for a year or more, so their cash comes in steadily
    # and a monthly charge matches it. Everything else earns once, at sale, and
    # is charged once per batch.
    return batch.bird_type.code == "layer"


def offer_for(batch: Batch, *, on: date | None = None) -> Offer:
    today = on or date.today()

    if _is_monthly(batch):
        # A renewal carries on from the end of what is already paid for, so
        # paying early never loses a day.
        current_end = access.covered_until(batch.farm, on=today)
        start = max(today, current_end + timedelta(days=1)) if current_end else today
        return Offer(
            kind=Payment.Kind.MONTH,
            amount=Decimal(settings.BILLING_MONTH_PRICE),
            covers_from=start,
            covers_until=start + timedelta(days=MONTH_DAYS - 1),
            description=f"Money tools for {batch.farm.name}, one month",
        )

    until = (
        batch.started_on
        + timedelta(days=batch.bird_type.cycle_days - 1)
        + timedelta(days=settings.BILLING_GRACE_DAYS)
    )
    return Offer(
        kind=Payment.Kind.BATCH,
        amount=Decimal(settings.BILLING_BATCH_PRICE),
        covers_from=batch.started_on,
        covers_until=until,
        description=f"Money tools for {batch.name}",
    )


def _refuse_if_pointless(batch: Batch, offer: Offer) -> None:
    """Never take money for days the farm already has."""
    if offer.kind == Payment.Kind.BATCH:
        already = Payment.objects.filter(
            batch=batch, kind=Payment.Kind.BATCH, status=Payment.Status.PAID
        ).exists()
        if already:
            raise DomainError(f"{batch.name} is already paid for.")

    current = access.for_farm(batch.farm)
    if current.active and current.until and current.until >= offer.covers_until:
        who = current.covered_by or "an earlier payment"
        raise DomainError(
            f"This farm is already covered by {who} until "
            f"{current.until:%-d %B %Y}. There is nothing to pay for yet."
        )


def _receipt_email(user) -> str:
    """
    The address Paystack requires, for farmers who sign in with a phone number.

    Built from the account id, never the phone number: it is handed to a third
    party and may appear on a receipt.
    """
    inbox = settings.PAYSTACK_RECEIPT_EMAIL
    if inbox and "@" in inbox:
        local, _, domain = inbox.partition("@")
        return f"{local}+{user.id.hex}@{domain}"
    return f"{user.id.hex}@{settings.PAYSTACK_EMAIL_DOMAIN}"


def start(*, farm: Farm, batch: Batch, user) -> Started:
    if batch.farm_id != farm.id:
        raise DomainError("That batch is not on this farm.")

    offer = offer_for(batch)
    _refuse_if_pointless(batch, offer)

    provider = get_provider()  # Raises before a row exists if payments are unconfigured.
    payment = Payment.objects.create(
        farm=farm,
        batch=batch,
        paid_by=user,
        kind=offer.kind,
        amount=offer.amount,
        reference=f"AV{uuid.uuid4().hex[:18].upper()}",
        provider=provider.name,
    )

    try:
        checkout = provider.initialize(
            email=_receipt_email(user),
            amount_kobo=payment.amount_kobo,
            reference=payment.reference,
            callback_url=f"{settings.FRONTEND_URL}/billing/done",
            metadata={"farm": str(farm.id), "batch": str(batch.id), "kind": offer.kind},
        )
    except ProviderUnavailable as exc:
        # Kept as a failed payment with the provider's reason, so whoever runs
        # the admin can see exactly why a farmer could not pay.
        payment.status = Payment.Status.FAILED
        payment.provider_response = {"stage": "start", "error": exc.provider_message}
        payment.save(update_fields=["status", "provider_response", "updated_at"])
        raise
    return Started(payment=payment, authorization_url=checkout.authorization_url)


def _provider_named(name: str):
    # Verify with whichever provider the payment was started on. A payment
    # begun against the fake provider must never be settled by asking Paystack.
    if name == FakeProvider.name:
        return FakeProvider()
    return PaystackProvider(settings.PAYSTACK_SECRET_KEY)


def confirm(reference: str) -> Payment:
    """
    Settle a payment by asking the provider, never by trusting the caller.

    Safe to call any number of times, from the browser returning and from the
    webhook arriving, in either order: the row is locked and a paid payment is
    returned as it is.
    """
    payment = Payment.objects.filter(reference=reference).first()
    if payment is None:
        raise DomainError("We have no record of that payment.")
    if payment.status == Payment.Status.PAID:
        return payment

    # Asked outside the lock: an HTTP call is too slow to hold a row for.
    result = _provider_named(payment.provider).verify(reference)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.Status.PAID:
            return payment

        payment.provider_response = result.raw

        amount_matches = result.amount_kobo == payment.amount_kobo
        currency_matches = (result.currency or payment.currency) == payment.currency

        if result.succeeded and amount_matches and currency_matches:
            offer = offer_for(payment.batch) if payment.batch else None
            payment.status = Payment.Status.PAID
            payment.paid_at = timezone.now()
            if offer:
                payment.covers_from = offer.covers_from
                payment.covers_until = offer.covers_until
        elif result.succeeded:
            # Money moved, but not the money we asked for. Do not unlock; this
            # needs a person to look at it.
            logger.warning(
                "Payment %s settled for %s %s, expected %s %s",
                reference,
                result.amount_kobo,
                result.currency,
                payment.amount_kobo,
                payment.currency,
            )
            payment.status = Payment.Status.FAILED
        elif result.failed:
            payment.status = Payment.Status.FAILED

        payment.save()
    return payment
