"""
An income statement for a calendar period.

The cycle report answers "did that batch make money". A lender asks a different
question: what did this farm earn and spend between two dates. This states that,
on a cash basis, from the records the farmer kept.

Two decisions matter for anyone reading it as evidence:

Nothing is estimated. Where a cost was never recorded it is absent and said to
be absent, rather than filled in from a market average. A statement that quietly
prices feed at a national figure is not evidence of anything.

The basis is declared. Every statement carries how complete the underlying
records are — days logged out of days in the period — so a lender can weigh it
without having to ask. Records that are thin say so on their face.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.farms.models import Farm
from apps.flocks.models import Batch, DailyLog, Sale


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if not whole:
        return Decimal("0.0")
    return (part / whole * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    label: str
    amount: Decimal
    pct_of_revenue: Decimal


@dataclass(frozen=True)
class BatchInPeriod:
    name: str
    bird_type: str
    started_on: date
    stocked: int
    sold: int
    status: str


@dataclass
class IncomeStatement:
    farm_name: str
    farm_location: str
    prepared_on: date
    starts_on: date
    ends_on: date

    revenue: Decimal
    revenue_lines: list[Line]

    cost_lines: list[Line]
    total_cost: Decimal

    gross_profit: Decimal
    margin: Decimal

    birds_sold: int
    kg_sold: Decimal
    revenue_per_bird: Decimal
    cost_per_bird: Decimal
    profit_per_bird: Decimal
    price_per_kg: Decimal | None

    # How much of the period the records actually cover. A lender is entitled
    # to know this without asking for it.
    days_in_period: int
    days_logged: int
    feed_cost_recorded: bool

    batches: list[BatchInPeriod] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


BASIS = [
    "Prepared on a cash basis: income is counted when birds were sold and costs "
    "when they were paid.",
    "Compiled by Aviro from the daily records kept by the farm. It has not been "
    "audited or reviewed by an accountant.",
]


def build(farm: Farm, *, starts_on: date, ends_on: date, on: date | None = None) -> IncomeStatement:
    """The farm's income and costs between two dates."""
    prepared_on = on or date.today()

    sales = list(
        Sale.objects.filter(batch__farm=farm, sold_on__gte=starts_on, sold_on__lte=ends_on)
    )
    revenue = sum((s.revenue for s in sales), Decimal("0"))
    birds_sold = sum(s.birds for s in sales)
    kg_sold = sum((s.birds * s.average_weight_kg for s in sales), Decimal("0"))

    # Chicks are a cost of the period they were bought in, which is the period
    # the batch was stocked.
    stocked_in_period = Batch.objects.filter(
        farm=farm, started_on__gte=starts_on, started_on__lte=ends_on
    )
    chicks = sum(
        (b.stocked * b.cost_per_bird for b in stocked_in_period),
        Decimal("0"),
    )
    transport = sum((b.transport_cost for b in stocked_in_period), Decimal("0"))

    logged = DailyLog.objects.filter(
        batch__farm=farm, logged_on__gte=starts_on, logged_on__lte=ends_on
    ).aggregate(feed=Sum("feed_cost"), meds=Sum("meds_cost"), other=Sum("other_cost"))
    feed = logged["feed"] or Decimal("0")
    meds = logged["meds"] or Decimal("0")
    other = logged["other"] or Decimal("0")

    cost_lines = [
        Line("Day-old chicks", _money(chicks), _pct(chicks, revenue)),
        Line("Feed", _money(feed), _pct(feed, revenue)),
        Line("Medication and vaccines", _money(meds), _pct(meds, revenue)),
        Line("Transport", _money(transport), _pct(transport, revenue)),
        Line("Other direct costs", _money(other), _pct(other, revenue)),
    ]
    cost_lines = [line for line in cost_lines if line.amount > 0]
    total_cost = sum((line.amount for line in cost_lines), Decimal("0"))

    revenue_lines = _revenue_by_buyer(sales, revenue)

    gross_profit = _money(revenue - total_cost)
    days_in_period = (ends_on - starts_on).days + 1
    days_logged = (
        DailyLog.objects.filter(
            batch__farm=farm, logged_on__gte=starts_on, logged_on__lte=ends_on
        )
        .values("logged_on")
        .distinct()
        .count()
    )

    statement = IncomeStatement(
        farm_name=farm.name,
        farm_location=farm.location,
        prepared_on=prepared_on,
        starts_on=starts_on,
        ends_on=ends_on,
        revenue=_money(revenue),
        revenue_lines=revenue_lines,
        cost_lines=cost_lines,
        total_cost=_money(total_cost),
        gross_profit=gross_profit,
        margin=_pct(gross_profit, revenue),
        birds_sold=birds_sold,
        kg_sold=kg_sold.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        revenue_per_bird=_money(revenue / birds_sold) if birds_sold else Decimal("0.00"),
        cost_per_bird=_money(total_cost / birds_sold) if birds_sold else Decimal("0.00"),
        profit_per_bird=_money(gross_profit / birds_sold) if birds_sold else Decimal("0.00"),
        price_per_kg=_money(revenue / kg_sold) if kg_sold else None,
        days_in_period=days_in_period,
        days_logged=days_logged,
        feed_cost_recorded=feed > 0,
        batches=[
            BatchInPeriod(
                name=b.name,
                bird_type=b.bird_type.label,
                started_on=b.started_on,
                stocked=b.stocked,
                sold=sum(s.birds for s in sales if s.batch_id == b.id),
                status=b.get_status_display(),
            )
            for b in Batch.objects.filter(farm=farm)
            .select_related("bird_type")
            .filter(started_on__lte=ends_on)
            .order_by("-started_on")
        ],
        basis=list(BASIS),
    )
    statement.limitations = _limitations(statement)
    return statement


def _revenue_by_buyer(sales, revenue: Decimal) -> list[Line]:
    """Split income by who bought, which is the first thing a lender looks for."""
    buckets: dict[str, Decimal] = {}
    for sale in sales:
        label = sale.get_buyer_type_display() if sale.buyer_type else "Unstated buyer"
        buckets[label] = buckets.get(label, Decimal("0")) + sale.revenue
    return [
        Line(label, _money(amount), _pct(amount, revenue))
        for label, amount in sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)
    ]


def _limitations(s: IncomeStatement) -> list[str]:
    """
    What this statement does not show.

    Written for the person reading it at a bank, not for the farmer. Naming the
    gaps is what makes the rest of the figures worth trusting.
    """
    notes = [
        "Birds alive at the end of the period are not valued. They appear as cost "
        "already incurred and as no income until they are sold.",
        "Housing, equipment, land and their depreciation are not included, nor is "
        "rent, interest, or the farmer's own labour unless it was recorded as a cost.",
    ]

    if not s.feed_cost_recorded and s.total_cost:
        notes.insert(
            0,
            "No feed purchases were recorded in this period, so feed does not appear "
            "as a cost. Feed is normally the largest single cost of poultry "
            "production, and profit shown here is overstated by its absence.",
        )

    if s.days_logged < s.days_in_period:
        missed = s.days_in_period - s.days_logged
        notes.append(
            f"Daily records exist for {s.days_logged} of {s.days_in_period} days in "
            f"the period; {missed} days were not recorded."
        )

    return notes


def month_to_date(today: date) -> tuple[date, date]:
    return today.replace(day=1), today


def last_full_month(today: date) -> tuple[date, date]:
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def year_to_date(today: date) -> tuple[date, date]:
    return today.replace(month=1, day=1), today


def trailing_year(today: date) -> tuple[date, date]:
    return today - timedelta(days=364), today
