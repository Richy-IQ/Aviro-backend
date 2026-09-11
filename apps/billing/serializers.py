from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from .models import CoopInvoice, Payment

# What the paid tools are, said the same way everywhere they are offered.
INCLUDED = [
    "Income statement you can print or take to a bank",
    "Download every daily record and sale as a spreadsheet",
    "Monthly report on how the farm is doing",
]

# And what never costs anything. Written down so it cannot quietly shrink.
ALWAYS_FREE = [
    "The feed and vaccination plan for every batch",
    "Daily logging, with today's feed target",
    "Warning signs when birds look sick",
    "Weight tracking against the target",
    "The weekly report",
    "The growing guide",
]


class AccessSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    source = serializers.CharField(allow_null=True)
    until = serializers.DateField(allow_null=True)
    covered_by = serializers.CharField(allow_null=True)


class OfferSerializer(serializers.Serializer):
    kind = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    covers_from = serializers.DateField()
    covers_until = serializers.DateField()
    description = serializers.CharField()


class PaymentSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source="batch.name", default=None)
    kind_label = serializers.CharField(source="get_kind_display")
    status_label = serializers.CharField(source="get_status_display")

    class Meta:
        model = Payment
        fields = [
            "id", "reference", "kind", "kind_label", "status", "status_label",
            "amount", "currency", "batch_name", "paid_at",
            "covers_from", "covers_until", "created_at",
        ]


class CoopInvoiceSerializer(serializers.ModelSerializer):
    organisation_name = serializers.CharField(source="organisation.name")
    status_label = serializers.CharField(source="get_status_display")
    bank = serializers.SerializerMethodField()

    class Meta:
        model = CoopInvoice
        fields = [
            "id", "number", "organisation_name", "status", "status_label",
            "period_start", "period_end", "farms_count", "price_per_farm", "amount",
            "issued_on", "due_on", "paid_on", "note", "bank",
        ]

    def get_bank(self, obj) -> dict:
        return dict(settings.BANK_TRANSFER_DETAILS)
