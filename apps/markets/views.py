"""Market endpoints. Read-only for farmers; prices are curated, not crowd-sourced."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Buyer, FeedPrice
from .serializers import BuyerSerializer, FeedPriceSerializer


class FeedPriceListView(APIView):
    """
    GET /api/v1/markets/feed-prices/?state=Oyo

    The latest price at each market, with its week-on-week movement. Filtered by
    state when given, because a price in Kano does not help a farmer in Ibadan.
    """

    def get(self, request: Request) -> Response:
        prices = FeedPrice.objects.select_related("market").order_by("market_id", "-recorded_on")
        if state := request.query_params.get("state"):
            prices = prices.filter(market__state__iexact=state)

        # One row per market: the most recent.
        latest: dict = {}
        for price in prices:
            latest.setdefault(price.market_id, price)

        week_ago = timezone.localdate() - timedelta(days=7)
        previous: dict = {}
        for price in FeedPrice.objects.filter(
            market_id__in=latest.keys(), recorded_on__lte=week_ago
        ).order_by("market_id", "-recorded_on"):
            previous.setdefault(price.market_id, price)

        serializer = FeedPriceSerializer(
            list(latest.values()), many=True, context={"previous_by_market": previous}
        )
        return Response(serializer.data)


class BuyerListView(APIView):
    """GET /api/v1/markets/buyers/?state=Oyo — buyers a farmer can approach."""

    def get(self, request: Request) -> Response:
        buyers = Buyer.objects.all()
        if state := request.query_params.get("state"):
            buyers = buyers.filter(state__iexact=state)
        return Response(BuyerSerializer(buyers, many=True).data)
