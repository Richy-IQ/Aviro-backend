"""
Cooperative invoices.

Drafted from the cooperative's current membership, sent, and marked paid by a
person when the transfer lands. There is no automation to go wrong between a
bank statement and a farmer's access, which at this size is a feature.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.farms.models import Organisation

from ..models import CoopInvoice

# One broiler cycle: the span a cooperative plans and pays in.
DEFAULT_PERIOD_DAYS = 42
PAYMENT_TERMS_DAYS = 14


def _next_number(year: int) -> str:
    prefix = f"AV-{year}-"
    last = (
        CoopInvoice.objects.filter(number__startswith=prefix)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


@transaction.atomic
def draft_for(
    organisation: Organisation,
    *,
    starts_on: date | None = None,
    days: int = DEFAULT_PERIOD_DAYS,
) -> CoopInvoice:
    start = starts_on or date.today()
    return CoopInvoice.objects.create(
        organisation=organisation,
        number=_next_number(start.year),
        period_start=start,
        period_end=start + timedelta(days=days - 1),
        farms_count=organisation.farms.count(),
        price_per_farm=Decimal(settings.BILLING_COOP_PRICE_PER_FARM),
        amount=Decimal("0"),  # Recomputed from its parts on save.
    )


def mark_sent(invoice: CoopInvoice, *, on: date | None = None) -> CoopInvoice:
    today = on or date.today()
    invoice.status = CoopInvoice.Status.SENT
    invoice.issued_on = invoice.issued_on or today
    invoice.due_on = invoice.due_on or today + timedelta(days=PAYMENT_TERMS_DAYS)
    invoice.save()
    return invoice


def mark_paid(invoice: CoopInvoice, *, on: date | None = None) -> CoopInvoice:
    invoice.status = CoopInvoice.Status.PAID
    invoice.paid_on = on or date.today()
    invoice.issued_on = invoice.issued_on or invoice.paid_on
    invoice.save()
    return invoice
