from django.urls import path

from .views import BuyerListView, FeedPriceListView

app_name = "markets"

urlpatterns = [
    path("feed-prices/", FeedPriceListView.as_view(), name="feed-prices"),
    path("buyers/", BuyerListView.as_view(), name="buyers"),
]
