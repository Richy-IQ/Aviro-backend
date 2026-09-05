"""Admin for feed prices and buyers — curated reference data, not user content."""

from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from .models import Buyer, FeedPrice, Market


class FeedPriceInline(admin.TabularInline):
    model = FeedPrice
    extra = 0
    fields = ["recorded_on", "starter", "grower", "finisher", "layer"]
    ordering = ["-recorded_on"]


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "lga", "price_count", "last_recorded"]
    list_filter = ["state"]
    search_fields = ["name", "state", "lga"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [FeedPriceInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).annotate(_prices=Count("feed_prices"))

    @admin.display(description="Price records", ordering="_prices")
    def price_count(self, market: Market) -> int:
        return market._prices

    @admin.display(description="Last recorded")
    def last_recorded(self, market: Market) -> str:
        latest = market.feed_prices.order_by("-recorded_on").first()
        if not latest:
            return format_html('<span style="color:#EF4444">never</span>')

        age = (timezone.localdate() - latest.recorded_on).days
        # Stale prices are worse than none: a farmer negotiates against them.
        colour = "#0F766E" if age <= 7 else "#F59E0B" if age <= 30 else "#EF4444"
        return format_html(
            '<span style="color:{}">{} ({} days ago)</span>', colour, latest.recorded_on, age
        )


@admin.register(FeedPrice)
class FeedPriceAdmin(admin.ModelAdmin):
    list_display = ["market", "recorded_on", "starter", "grower", "finisher", "layer", "movement"]
    list_filter = ["recorded_on", "market__state", "market"]
    search_fields = ["market__name", "market__state"]
    autocomplete_fields = ["market"]
    date_hierarchy = "recorded_on"
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("market")

    @admin.display(description="Grower, week on week")
    def movement(self, price: FeedPrice) -> str:
        """The change is what changes a decision, not the absolute number."""
        if not price.grower:
            return "—"
        previous = (
            FeedPrice.objects.filter(
                market=price.market, recorded_on__lte=price.recorded_on - timedelta(days=7)
            )
            .order_by("-recorded_on")
            .first()
        )
        if not previous or not previous.grower:
            return "—"

        change = (price.grower - previous.grower) / previous.grower * 100
        colour = "#EF4444" if change > 0 else "#0F766E"
        return format_html('<span style="color:{}">{:+.1f}%</span>', colour, change)


@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "lga", "typical_price_per_kg", "verified"]
    list_filter = ["verified", "state"]
    search_fields = ["name", "state", "lga"]
    list_editable = ["verified"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("id", "name", "verified")}),
        ("Where", {"fields": ("state", "lga")}),
        (
            "Pricing",
            {
                "fields": ("typical_price_per_kg",),
                "description": "Shown to farmers as a guide before they negotiate.",
            },
        ),
    )
