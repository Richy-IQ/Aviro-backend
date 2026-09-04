from rest_framework import serializers

from .models import Buyer, FeedPrice, Market


class MarketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Market
        fields = ["id", "name", "state", "lga"]


class FeedPriceSerializer(serializers.ModelSerializer):
    market = MarketSerializer(read_only=True)
    trend_pct = serializers.SerializerMethodField()

    class Meta:
        model = FeedPrice
        fields = [
            "id", "market", "recorded_on",
            "starter", "grower", "finisher", "layer",
            "trend_pct",
        ]

    def get_trend_pct(self, price: FeedPrice) -> float | None:
        """Week-on-week movement in grower feed — the change is what matters."""
        previous = self.context.get("previous_by_market", {}).get(price.market_id)
        if not previous or not previous.grower or not price.grower:
            return None
        return round(float((price.grower - previous.grower) / previous.grower * 100), 1)


class BuyerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Buyer
        fields = ["id", "name", "state", "lga", "typical_price_per_kg", "verified"]
