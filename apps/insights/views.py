"""Insight endpoints: alerts and benchmarks."""

from __future__ import annotations

from dataclasses import asdict

from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm
from apps.farms.permissions import IsFarmMember
from apps.flocks.models import Batch
from apps.flocks.services import metrics as metrics_service

from .services import alerts as alert_service
from .services import benchmarks as benchmark_service


class FarmAlertsView(APIView):
    """
    GET /api/v1/farms/<farm_id>/alerts/

    Everything needing attention across the farm's active batches, most urgent
    first, so the client can render the list without sorting.
    """

    permission_classes = [IsFarmMember]
    SEVERITY = {"error": 0, "warn": 1, "success": 2, "info": 3}

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        batches = Batch.objects.filter(
            farm=self.get_farm(), status=Batch.Status.ACTIVE
        ).select_related("bird_type")

        alerts = [alert for batch in batches for alert in alert_service.for_batch(batch)]
        alerts.sort(key=lambda a: self.SEVERITY.get(a.kind, 9))
        return Response([asdict(alert) for alert in alerts])


class BatchBenchmarkView(APIView):
    """
    GET /api/v1/farms/<farm_id>/batches/<batch_id>/benchmark/

    How this batch compares with others of the same bird type. Percentiles come
    from real batches once there are enough of them, and from published industry
    figures until then — and the response says which, because a farmer deserves
    to know whether they are being compared with their neighbours or a textbook.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id, batch_id) -> Response:
        batch = get_object_or_404(Batch, pk=batch_id, farm=self.get_farm())
        metrics = metrics_service.compute(batch)
        return Response(benchmark_service.compare(batch, metrics))
