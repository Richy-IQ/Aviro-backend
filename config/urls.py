"""
Root URL configuration.

Every application endpoint lives under /api/. The version prefix is deliberate:
a mobile client that a farmer has not updated in months must keep working, and
that is far easier when v1 can stay frozen while v2 is added beside it.
"""

from django.contrib import admin
from django.urls import include, path

from apps.common.views import HealthView

admin.site.site_header = "Aviro administration"
admin.site.site_title = "Aviro"
admin.site.index_title = "Farms, flocks and markets"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/farms/", include("apps.farms.urls")),
    path("api/v1/", include("apps.flocks.urls")),
    path("api/v1/", include("apps.insights.urls")),
    path("api/v1/markets/", include("apps.markets.urls")),
    path("api/v1/", include("apps.billing.urls")),
]
