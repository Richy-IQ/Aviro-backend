from django.urls import path

from .views import (
    BatchBenchmarkView,
    CycleReportDetailView,
    CycleReportListView,
    FarmAlertsView,
)

app_name = "insights"

urlpatterns = [
    path("farms/<uuid:farm_id>/alerts/", FarmAlertsView.as_view(), name="alerts"),
    path("farms/<uuid:farm_id>/reports/", CycleReportListView.as_view(), name="reports"),
    path(
        "farms/<uuid:farm_id>/reports/<uuid:batch_id>/",
        CycleReportDetailView.as_view(),
        name="report-detail",
    ),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/benchmark/",
        BatchBenchmarkView.as_view(),
        name="benchmark",
    ),
]
