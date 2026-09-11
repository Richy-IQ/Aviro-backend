"""
What a farm has paid for, and what a cooperative owes.

Everything to do with the birds is free and stays free: the plan, the daily log,
the guide, the warnings, the weekly report. What is paid for is the paperwork —
the income statement a bank asks for, the records a lender wants to check, the
monthly report. A payment buys a span of days in which the farm has those tools.

The span is the product, not the payment. A broiler farmer pays once for a
batch and is covered for that cycle and the weeks after it, which is when the
statement is actually needed. A layer farmer, whose birds earn every week for a
year, pays by the month. A cooperative pays for all of its members at once.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Payment(BaseModel):
    """One attempt to pay, from checkout to confirmation."""

    class Kind(models.TextChoices):
        BATCH = "batch", "One batch"
        MONTH = "month", "One month"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    farm = models.ForeignKey("farms.Farm", on_delete=models.CASCADE, related_name="payments")
    batch = models.ForeignKey(
        "flocks.Batch", on_delete=models.SET_NULL, null=True, related_name="payments"
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="payments"
    )

    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")

    # Ours, sent to the provider and echoed back. Unique, so a webhook and a
    # browser callback arriving together can only ever settle one row.
    reference = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Set when the payment is confirmed, never before. A pending payment covers
    # nothing.
    covers_from = models.DateField(null=True, blank=True)
    covers_until = models.DateField(null=True, blank=True)

    # What the provider said when we checked, kept for disputes.
    provider_response = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "billing_payment"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["farm", "status", "covers_until"])]

    def __str__(self) -> str:
        return f"{self.reference} · {self.get_status_display()} · ₦{self.amount}"

    @property
    def amount_kobo(self) -> int:
        """Paystack counts in kobo. Integer, so a comparison is exact."""
        return int((self.amount * 100).to_integral_value())


class CoopInvoice(BaseModel):
    """
    A cooperative's bill for a span of days, paid by bank transfer.

    Settled by hand in the admin when the money arrives, because that is how a
    cooperative pays: one transfer against an invoice number, not fifty card
    payments.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    organisation = models.ForeignKey(
        "farms.Organisation", on_delete=models.CASCADE, related_name="invoices"
    )
    number = models.CharField(max_length=20, unique=True)

    period_start = models.DateField(help_text="First day member farms are covered.")
    period_end = models.DateField(help_text="Last day member farms are covered.")

    farms_count = models.PositiveIntegerField()
    price_per_farm = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    issued_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "billing_coop_invoice"
        ordering = ["-period_start"]

    def __str__(self) -> str:
        return f"{self.number} · {self.organisation} · ₦{self.amount}"

    def save(self, *args, **kwargs):
        # The total follows from its parts, so it cannot drift from them.
        self.amount = (Decimal(self.farms_count) * self.price_per_farm).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
