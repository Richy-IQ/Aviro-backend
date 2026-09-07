"""Insight endpoints: alerts and benchmarks."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError
from apps.farms.models import Farm
from apps.farms.permissions import IsFarmMember
from apps.flocks.models import Batch
from apps.flocks.services import metrics as metrics_service

from .serializers import (
    CycleReportSerializer,
    IncomeStatementSerializer,
    PeriodReportSerializer,
)
from .services import alerts as alert_service
from .services import benchmarks as benchmark_service
from .services import exports as export_service
from .services import period as period_service
from .services import reports as report_service
from .services import statement as statement_service


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


class CycleReportListView(APIView):
    """
    GET /api/v1/farms/<farm_id>/reports/?period=12-mo&include_open=true

    Every cycle in the period, newest first, each stated as revenue less cost
    of production. Open cycles are included by default and flagged as
    projections, because a farmer wants to see the batch they are running now
    alongside the ones they have finished.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        self.get_farm()

        period = request.query_params.get("period", "12-mo")
        if period not in report_service.PERIODS:
            period = "12-mo"
        include_open = request.query_params.get("include_open", "true").lower() != "false"

        cycles = report_service.for_farm(farm_id, period=period, include_open=include_open)
        serialized = CycleReportSerializer(cycles, many=True).data

        # Totals are summed from the same reports the client is about to
        # render, so the header can never disagree with the rows beneath it.
        revenue = sum(c.revenue for c in cycles)
        total_cost = sum(c.total_cost for c in cycles)
        gross_profit = revenue - total_cost

        return Response(
            {
                "period": period,
                "cycles": serialized,
                "totals": {
                    "revenue": str(revenue),
                    "total_cost": str(total_cost),
                    "gross_profit": str(gross_profit),
                    "margin": str(
                        (gross_profit / revenue * 100).quantize(Decimal("0.1"))
                        if revenue
                        else Decimal("0.0")
                    ),
                    "birds_sold": sum(c.sold for c in cycles),
                    "closed_cycles": sum(1 for c in cycles if c.is_closed),
                },
            }
        )


class CycleReportDetailView(APIView):
    """
    GET /api/v1/farms/<farm_id>/reports/<batch_id>/

    One cycle in full, with the observations that go with it.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id, batch_id) -> Response:
        batch = get_object_or_404(
            Batch.objects.select_related("bird_type", "breed"),
            pk=batch_id,
            farm=self.get_farm(),
        )

        # Compare against the cycle that closed before this one started, which
        # is what makes "cost per bird is down 8%" a real statement.
        previous_batch = (
            Batch.objects.filter(
                farm_id=farm_id,
                status=Batch.Status.CLOSED,
                started_on__lt=batch.started_on,
            )
            .order_by("-started_on")
            .first()
        )
        previous = report_service.build(previous_batch) if previous_batch else None

        return Response(CycleReportSerializer(report_service.build(batch, previous=previous)).data)


class FarmPeriodReportView(APIView):
    """
    GET /api/v1/farms/<farm_id>/summary/?period=week

    How the farm is doing right now, rather than how a finished batch did.
    Counted from what was logged and compared with the window before it, so
    fourteen deaths reads as better or worse rather than just as fourteen.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        self.get_farm()

        period = request.query_params.get("period", "week")
        if period not in period_service.PERIODS:
            period = "week"

        summary = period_service.build(farm_id, period=period)
        return Response(PeriodReportSerializer(summary).data)


def _range(request: Request) -> tuple[date, date]:
    """
    The period a statement or export covers.

    `from` and `to` win when both are given; otherwise a named window, so the
    common cases are one tap and the unusual ones are still reachable.
    """
    today = timezone.localdate()
    named = {
        "this-month": statement_service.month_to_date,
        "last-month": statement_service.last_full_month,
        "this-year": statement_service.year_to_date,
        "12-mo": statement_service.trailing_year,
    }

    raw_from = request.query_params.get("from")
    raw_to = request.query_params.get("to")
    if raw_from and raw_to:
        starts_on, ends_on = parse_date(raw_from), parse_date(raw_to)
        if starts_on is None or ends_on is None:
            raise DomainError("`from` and `to` must be dates, as YYYY-MM-DD.")
        if ends_on < starts_on:
            raise DomainError("The period ends before it starts.")
        return starts_on, ends_on

    window = named.get(request.query_params.get("period", "12-mo"), statement_service.trailing_year)
    return window(today)


class FarmStatementView(APIView):
    """
    GET /api/v1/farms/<farm_id>/statement/?period=this-year

    A cash-basis income statement for a calendar period, for a farmer who has
    been asked for one. Nothing on it is estimated, and it carries how complete
    the underlying records are so the reader can weigh it.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        farm = self.get_farm()
        starts_on, ends_on = _range(request)
        statement = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)
        return Response(IncomeStatementSerializer(statement).data)


class FarmRecordsExportView(APIView):
    """
    GET /api/v1/farms/<farm_id>/records/?dataset=logs&period=this-month

    The rows themselves, as CSV. Raw and underived: a figure someone can
    recompute is worth more than one they have to trust.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> HttpResponse:
        farm = self.get_farm()
        dataset = request.query_params.get("dataset", "logs")
        if dataset not in export_service.DATASETS:
            raise DomainError("`dataset` must be either `logs` or `sales`.")

        starts_on, ends_on = _range(request)
        body, filename = export_service.build(
            farm, dataset=dataset, starts_on=starts_on, ends_on=ends_on
        )
        response = HttpResponse(body, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
