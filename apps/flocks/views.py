"""
Flock endpoints.

Each view is an APIView with explicit methods. Views stay thin: they resolve
the farm, check the membership, validate input, and hand the work to a service
or the ORM. Business rules live in services/, not here.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError
from apps.farms.models import Farm
from apps.farms.permissions import IsFarmMember

from .models import Batch, BirdType, DailyLog, Sale
from .serializers import (
    BatchSerializer,
    BirdTypeSerializer,
    DailyLogSerializer,
    MetricsSerializer,
    SaleSerializer,
    VaccinationScheduleSerializer,
)
from .services import metrics as metrics_service


class FarmScopedView(APIView):
    """
    Base for anything hanging off a farm.

    Resolving the farm in one place means every subclass gets the same
    authorisation check, and none of them can forget it.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get_batch(self) -> Batch:
        return get_object_or_404(Batch, pk=self.kwargs["batch_id"], farm=self.get_farm())


class BirdTypeListView(APIView):
    """
    GET /api/v1/bird-types/

    Reference data: the kinds of bird Aviro supports and the cycle each one
    implies. Needed before a farmer can create their first batch.
    """

    def get(self, request: Request) -> Response:
        types = BirdType.objects.prefetch_related("breeds").all()
        return Response(BirdTypeSerializer(types, many=True).data)


class VaccinationScheduleView(APIView):
    """
    GET /api/v1/bird-types/<code>/vaccinations/

    Scoped to the bird type, so a layer keeper is never shown broiler dates.
    """

    def get(self, request: Request, code: str) -> Response:
        bird_type = get_object_or_404(BirdType, code=code)
        schedule = bird_type.vaccination_schedule.all()
        return Response(VaccinationScheduleSerializer(schedule, many=True).data)


class BatchListView(FarmScopedView):
    """
    GET  /api/v1/farms/<farm_id>/batches/ — batches on this farm.
    POST /api/v1/farms/<farm_id>/batches/ — start a new one.
    """

    def get(self, request: Request, farm_id) -> Response:
        batches = (
            Batch.objects.filter(farm=self.get_farm())
            .select_related("bird_type", "breed", "pen")
            .order_by("-started_on")
        )
        if request.query_params.get("status"):
            batches = batches.filter(status=request.query_params["status"])
        return Response(BatchSerializer(batches, many=True).data)

    def post(self, request: Request, farm_id) -> Response:
        serializer = BatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save(farm=self.get_farm())
        return Response(BatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class BatchDetailView(FarmScopedView):
    """
    GET   /api/v1/farms/<farm_id>/batches/<batch_id>/
    PATCH /api/v1/farms/<farm_id>/batches/<batch_id>/

    The response carries the batch and its derived metrics together, because
    the batch screen needs both and a second round trip on a slow connection is
    a second chance to fail.
    """

    def get(self, request: Request, farm_id, batch_id) -> Response:
        batch = self.get_batch()
        return Response(
            {
                "batch": BatchSerializer(batch).data,
                "metrics": MetricsSerializer(metrics_service.compute(batch)).data,
            }
        )

    def patch(self, request: Request, farm_id, batch_id) -> Response:
        batch = self.get_batch()
        serializer = BatchSerializer(batch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(BatchSerializer(batch).data)


class DailyLogListView(FarmScopedView):
    """
    GET  /api/v1/farms/<farm_id>/batches/<batch_id>/logs/
    POST /api/v1/farms/<farm_id>/batches/<batch_id>/logs/

    Posting for a date that is already logged updates it. A farmer who cannot
    remember whether they logged should be able to just log again, and this is
    also what makes an offline queue safe to replay.
    """

    def get(self, request: Request, farm_id, batch_id) -> Response:
        logs = DailyLog.objects.filter(batch=self.get_batch()).order_by("-logged_on")
        return Response(DailyLogSerializer(logs, many=True).data)

    @transaction.atomic
    def post(self, request: Request, farm_id, batch_id) -> Response:
        batch = self.get_batch()
        if batch.status == Batch.Status.CLOSED:
            raise DomainError("This batch is closed. Reopen it before logging.")

        serializer = DailyLogSerializer(data=request.data, context={"batch": batch})
        serializer.is_valid(raise_exception=True)

        existing = DailyLog.objects.filter(
            batch=batch, logged_on=serializer.validated_data["logged_on"]
        ).first()
        if existing:
            serializer = DailyLogSerializer(
                existing, data=request.data, partial=True, context={"batch": batch}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        log = serializer.save(batch=batch)
        return Response(DailyLogSerializer(log).data, status=status.HTTP_201_CREATED)


class SaleListView(FarmScopedView):
    """
    GET  /api/v1/farms/<farm_id>/batches/<batch_id>/sales/
    POST /api/v1/farms/<farm_id>/batches/<batch_id>/sales/

    A full sale closes the batch, which is what turns an open projection into a
    settled cycle in the reports.
    """

    def get(self, request: Request, farm_id, batch_id) -> Response:
        sales = Sale.objects.filter(batch=self.get_batch()).order_by("-sold_on")
        return Response(SaleSerializer(sales, many=True).data)

    @transaction.atomic
    def post(self, request: Request, farm_id, batch_id) -> Response:
        batch = self.get_batch()
        if batch.status == Batch.Status.CLOSED:
            raise DomainError("This batch is already closed.")

        serializer = SaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        current = metrics_service.compute(batch)
        if serializer.validated_data["birds"] > current.alive:
            raise DomainError(
                f"You have {current.alive} birds alive in {batch.name}, "
                f"so you cannot sell {serializer.validated_data['birds']}."
            )

        sale = serializer.save(batch=batch)

        if sale.kind == Sale.Kind.FULL:
            batch.status = Batch.Status.CLOSED
            batch.closed_on = sale.sold_on or timezone.localdate()
            batch.save(update_fields=["status", "closed_on", "updated_at"])

        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)
