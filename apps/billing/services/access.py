"""
Whether a farm has the paid tools today, and why.

Answered in one place, because everything that is paid for — the statement,
the downloads, the monthly report — must agree on it. The reason travels with
the answer so the screen can say "covered by Ibadan Poultry Cooperative until
12 October" rather than a bare yes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rest_framework import status
from rest_framework.exceptions import APIException

from apps.farms.models import Farm

from ..models import CoopInvoice, Payment


class PaymentRequired(APIException):
    """A paid tool, asked for by a farm that is not covered."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "This is part of Aviro's money tools. Unlock them for this batch to continue."
    default_code = "payment_required"


@dataclass(frozen=True)
class Access:
    active: bool
    # "batch", "month" or "cooperative". None when not covered.
    source: str | None
    until: date | None
    # A batch name or a cooperative name, for the sentence on screen.
    covered_by: str | None


NOT_COVERED = Access(active=False, source=None, until=None, covered_by=None)


def for_farm(farm: Farm, *, on: date | None = None) -> Access:
    today = on or date.today()
    candidates: list[Access] = []

    payment = (
        Payment.objects.filter(
            farm=farm,
            status=Payment.Status.PAID,
            covers_from__lte=today,
            covers_until__gte=today,
        )
        .select_related("batch")
        .order_by("-covers_until")
        .first()
    )
    if payment:
        candidates.append(
            Access(
                active=True,
                source=payment.kind,
                until=payment.covers_until,
                covered_by=payment.batch.name if payment.batch else None,
            )
        )

    if farm.organisation_id:
        invoice = (
            CoopInvoice.objects.filter(
                organisation_id=farm.organisation_id,
                status=CoopInvoice.Status.PAID,
                period_start__lte=today,
                period_end__gte=today,
            )
            .select_related("organisation")
            .order_by("-period_end")
            .first()
        )
        if invoice:
            candidates.append(
                Access(
                    active=True,
                    source="cooperative",
                    until=invoice.period_end,
                    covered_by=invoice.organisation.name,
                )
            )

    if not candidates:
        return NOT_COVERED
    # Whichever lasts longest is the one worth telling the farmer about.
    return max(candidates, key=lambda a: a.until)


def covered_until(farm: Farm, *, on: date | None = None) -> date | None:
    access = for_farm(farm, on=on)
    return access.until if access.active else None


def require(farm: Farm) -> None:
    """Raise a 402 unless the farm is covered today."""
    if not for_farm(farm).active:
        raise PaymentRequired()
