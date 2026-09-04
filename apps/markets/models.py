"""
What things cost, and who is buying.

Prices are recorded as a series rather than overwritten, so a farmer can see
that feed has moved 4% this week — which is the part that changes a decision,
not today's absolute number.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class Market(BaseModel):
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=60)
    lga = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = "markets_market"
        ordering = ["state", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "state"], name="unique_market_per_state"),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.state}"


class FeedPrice(BaseModel):
    """Feed price per kilogram at one market on one day."""

    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name="feed_prices")
    recorded_on = models.DateField()

    starter = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    grower = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    finisher = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    layer = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "markets_feed_price"
        ordering = ["-recorded_on", "market__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["market", "recorded_on"], name="one_feed_price_per_market_per_day"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.market.name} — {self.recorded_on}"


class Buyer(BaseModel):
    """Someone who buys birds, listed so farmers are not negotiating with one offer."""

    name = models.CharField(max_length=120)
    state = models.CharField(max_length=60)
    lga = models.CharField(max_length=60, blank=True)
    typical_price_per_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    verified = models.BooleanField(default=False)

    class Meta:
        db_table = "markets_buyer"
        ordering = ["-verified", "name"]

    def __str__(self) -> str:
        return self.name
