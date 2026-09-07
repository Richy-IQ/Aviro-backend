from django.urls import path

from .views import (
    BatchDetailView,
    BatchListView,
    BatchPlanView,
    BirdTypeListView,
    CyclePlanPreviewView,
    DailyLogListView,
    SaleListView,
    VaccinationScheduleView,
)

app_name = "flocks"

urlpatterns = [
    path("bird-types/", BirdTypeListView.as_view(), name="bird-types"),
    path("bird-types/<str:code>/plan/", CyclePlanPreviewView.as_view(), name="plan-preview"),
    path(
        "bird-types/<str:code>/vaccinations/",
        VaccinationScheduleView.as_view(),
        name="vaccination-schedule",
    ),
    path("farms/<uuid:farm_id>/batches/", BatchListView.as_view(), name="batch-list"),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/",
        BatchDetailView.as_view(),
        name="batch-detail",
    ),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/plan/",
        BatchPlanView.as_view(),
        name="batch-plan",
    ),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/logs/",
        DailyLogListView.as_view(),
        name="log-list",
    ),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/sales/",
        SaleListView.as_view(),
        name="sale-list",
    ),
]
