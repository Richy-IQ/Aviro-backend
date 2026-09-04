from django.urls import path

from .views import FarmDetailView, FarmListView, PenListView, TeamView

app_name = "farms"

urlpatterns = [
    path("", FarmListView.as_view(), name="farm-list"),
    path("<uuid:farm_id>/", FarmDetailView.as_view(), name="farm-detail"),
    path("<uuid:farm_id>/pens/", PenListView.as_view(), name="pen-list"),
    path("<uuid:farm_id>/team/", TeamView.as_view(), name="team"),
]
