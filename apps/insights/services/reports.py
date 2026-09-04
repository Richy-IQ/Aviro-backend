"""
Cycle reports and the income statement.

A cycle report answers "what did this batch actually earn me?" once the birds
are sold. The income statement answers the same question across cycles, in the
shape a cooperative or a lender expects to read.

Both are derived from the logs and sales, never stored, so a corrected entry
corrects the report too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.flocks.models import Batch
from apps.flocks.services import metrics as metrics_service

# Benchmarks used to phrase the observations. These match the figures the
# benchmark screen compares against, so the two never contradict each other.
GOOD_MORTALITY_PCT = Decimal("5")
GOOD_FCR = Decimal("1.7")

PERIODS = {
    "6-mo": 182,
    "12-mo": 365,
    "all": None,
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if not whole:
        return Decimal("0.0")
    return (part / whole * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostLine:
    category: str
    amount: Decimal
    pct_of_revenue: Decimal


@dataclass
class CycleReport:
    """One batch, from stocking to sale."""

    batch_id: str
    name: str
    breed: str
    bird_type: str

    started_on: date
    closed_on: date | None
    days: int
    is_closed: bool

    stocked: int
    sold: int
    mortality_pct: Decimal
    average_weight_kg: Decimal | None
    feed_conversion: Decimal | None

    revenue: Decimal
    costs: list[CostLine]
    total_cost: Decimal
    gross_profit: Decimal
    margin: Decimal

    cost_per_bird: Decimal
    revenue_per_bird: Decimal
    profit_per_bird: Decimal
    cost_per_kg: Decimal | None
    price_per_kg: Decimal | None

    insights: list[str] = field(default_factory=list)


def build(batch: Batch, *, previous: Batch | None = None) -> CycleReport:
    """
    State one cycle.

    An open batch is stated at projection rather than fact, and says so — a
    lender must not read a projection as booked income.
    """
    closed = batch.status == Batch.Status.CLOSED
    as_at = batch.closed_on if closed and batch.closed_on else date.today()
    m = metrics_service.compute(batch, on=as_at)

    logs = batch.logs.filter(logged_on__lte=as_at)
    sales = batch.sales.filter(sold_on__lte=as_at)

    totals = logs.aggregate(
        feed=Sum("feed_cost"), meds=Sum("meds_cost"), other=Sum("other_cost")
    )
    feed = totals["feed"] or Decimal("0")
    meds = totals["meds"] or Decimal("0")
    other = totals["other"] or Decimal("0")
    chicks = batch.cost_per_bird * batch.stocked
    transport = batch.transport_cost

    sold = sales.aggregate(birds=Sum("birds"))["birds"] or 0
    booked = sales.aggregate(total=Sum("revenue"))["total"] or Decimal("0")

    # Closed cycles are stated on money actually received. An open cycle has
    # birds still in the pen, so its revenue is what they would fetch today.
    revenue = booked if closed else (m.projected_revenue or booked)

    costs = [
        CostLine("Chicks", _money(chicks), _pct(chicks, revenue)),
        CostLine("Feed", _money(feed), _pct(feed, revenue)),
        CostLine("Medication", _money(meds), _pct(meds, revenue)),
        CostLine("Transport", _money(transport), _pct(transport, revenue)),
        CostLine("Other", _money(other), _pct(other, revenue)),
    ]
    costs = [line for line in costs if line.amount > 0]

    total_cost = _money(chicks + feed + meds + transport + other)
    gross_profit = _money(revenue - total_cost)

    # Per-bird figures divide by the birds that earned the money. For a closed
    # cycle that is the birds sold; for an open one, the birds still alive.
    earning_birds = sold if closed and sold else m.alive or 1

    weight = _weighted_average_weight(batch, as_at) or m.average_weight_kg
    total_kg = Decimal(earning_birds) * weight if weight else None

    report = CycleReport(
        batch_id=str(batch.id),
        name=batch.name,
        breed=batch.breed.name if batch.breed else "—",
        bird_type=batch.bird_type.code,
        started_on=batch.started_on,
        closed_on=batch.closed_on,
        days=(as_at - batch.started_on).days + 1,
        is_closed=closed,
        stocked=batch.stocked,
        sold=sold,
        mortality_pct=m.mortality_pct,
        average_weight_kg=weight,
        feed_conversion=m.feed_conversion,
        revenue=_money(revenue),
        costs=costs,
        total_cost=total_cost,
        gross_profit=gross_profit,
        margin=_pct(gross_profit, revenue),
        cost_per_bird=_money(total_cost / earning_birds),
        revenue_per_bird=_money(revenue / earning_birds),
        profit_per_bird=_money(gross_profit / earning_birds),
        cost_per_kg=_money(total_cost / total_kg) if total_kg else None,
        price_per_kg=_money(revenue / total_kg) if total_kg else None,
    )
    report.insights = _observe(report, previous)
    return report


def _weighted_average_weight(batch: Batch, as_at: date) -> Decimal | None:
    """Average weight across the sales, weighted by how many birds each moved."""
    sales = list(batch.sales.filter(sold_on__lte=as_at))
    birds = sum(s.birds for s in sales)
    if not birds:
        return None
    total = sum(s.birds * s.average_weight_kg for s in sales)
    return (total / birds).quantize(Decimal("0.01"))


def _observe(report: CycleReport, previous: CycleReport | Batch | None) -> list[str]:
    """
    Plain observations a farmer can act on.

    Only things the data actually supports — no encouragement, and no claim
    that cannot be traced back to a number on the same page.
    """
    notes: list[str] = []

    # Name the cost that actually dominated, rather than asserting which one
    # usually does — the sentence has to survive being read beside the table.
    if report.costs and report.revenue:
        largest = max(report.costs, key=lambda c: c.amount)
        share_of_cost = _pct(largest.amount, report.total_cost)
        notes.append(
            f"{largest.category} was your biggest cost at {_naira(largest.amount)} — "
            f"{share_of_cost}% of everything you spent, and "
            f"{largest.pct_of_revenue}% of what you earned."
        )

    if report.mortality_pct > GOOD_MORTALITY_PCT:
        lost = report.stocked - report.sold if report.is_closed else None
        detail = f" That is {lost} birds." if lost else ""
        notes.append(
            f"Mortality was {report.mortality_pct}%, above the 5% that a good "
            f"cycle stays under.{detail}"
        )
    else:
        notes.append(f"Mortality held at {report.mortality_pct}%, inside the 5% mark.")

    if report.feed_conversion is not None:
        if report.feed_conversion > GOOD_FCR:
            notes.append(
                f"Feed conversion was {report.feed_conversion} — above 1.7, so the birds "
                f"ate more than they needed to for the weight they put on."
            )
        else:
            notes.append(
                f"Feed conversion was {report.feed_conversion}, at or under the 1.7 "
                f"that marks a well-run cycle."
            )

    if isinstance(previous, CycleReport) and previous.cost_per_bird:
        delta = report.cost_per_bird - previous.cost_per_bird
        pct = _pct(abs(delta), previous.cost_per_bird)
        if abs(pct) >= Decimal("1"):
            direction = "up" if delta > 0 else "down"
            notes.append(
                f"Cost per bird is {direction} {pct}% on {previous.name} "
                f"({_naira(previous.cost_per_bird)} → {_naira(report.cost_per_bird)})."
            )

    if not report.is_closed:
        notes.append(
            "This cycle is still running, so these figures are a projection at "
            "today's market price, not money received."
        )

    return notes


def _naira(value: Decimal) -> str:
    return f"₦{value:,.0f}"


def for_farm(farm_id, *, period: str = "12-mo", include_open: bool = True) -> list[CycleReport]:
    """
    Every cycle in the period, newest first.

    Reports are built oldest-first so each can be compared with the one before
    it, then reversed for display.
    """
    batches = (
        Batch.objects.filter(farm_id=farm_id)
        .select_related("bird_type", "breed")
        .prefetch_related("logs", "sales")
        .order_by("started_on")
    )
    if not include_open:
        batches = batches.filter(status=Batch.Status.CLOSED)

    days = PERIODS.get(period, 365)
    if days is not None:
        batches = batches.filter(started_on__gte=date.today() - timedelta(days=days))

    reports: list[CycleReport] = []
    previous: CycleReport | None = None
    for batch in batches:
        report = build(batch, previous=previous)
        reports.append(report)
        if report.is_closed:
            previous = report

    return list(reversed(reports))
