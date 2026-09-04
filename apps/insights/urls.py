from django.urls import path

from .views import BatchBenchmarkView, FarmAlertsView

app_name = "insights"

urlpatterns = [
    path("farms/<uuid:farm_id>/alerts/", FarmAlertsView.as_view(), name="alerts"),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/benchmark/",
        BatchBenchmarkView.as_view(),
        name="benchmark",
    ),
]
