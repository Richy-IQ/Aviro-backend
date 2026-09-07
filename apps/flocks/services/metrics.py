"""
Derived numbers for a batch.

These are the figures a farmer makes decisions on — what a bird costs, how
efficiently feed is converting, when to sell — so they are computed here as
pure functions over the logs rather than stored on the batch. Storing them
would let a corrected log and a stale metric disagree, and the farmer would
have no way of knowing which to trust.

All money is Decimal. Floats are fine for weight and ratios; they are not fine
for naira.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from django.db.models import Sum

from ..models import Batch

# Where a market price is needed and none is known, this is the fallback used
# for projections. It belongs in configuration eventually, not in code.
DEFAULT_PRICE_PER_KG = Decimal("3200")

# A bird eats roughly 5.5% of its body weight each day. Because intake scales
# with weight while daily gain eventually slows, this is what creates an
# economic optimum rather than "later is always better".
PROJECTED_DAILY_FEED_RATIO = Decimal("0.055")
PROJECTED_FEED_PRICE_PER_KG = Decimal("720")

# Gompertz growth: W(t) = A·exp(-B·exp(-k·t)). Fitted so a Cobb 500 is about
# 45g on day one and 2.5kg on day 42. A plateauing curve matters — an
# ever-accelerating one would say "sell later" forever, which is the opposite
# of useful.
GOMPERTZ_MATURE_KG = Decimal("4.5")
GOMPERTZ_B = Decimal("4.8423")
GOMPERTZ_K = Decimal("0.0502")

# Feed conversion before the birds have any real mass is arithmetic noise: a
# day-old chick weighs 45g, so a single bag of feed produces a ratio of 5 and a
# "behind" verdict on a flock that is doing nothing wrong. Withhold it until
# the number means something.
FCR_MEANINGFUL_FROM_DAY = 7

# How far past the nominal cycle to look. Broiler economics can stay positive
# for some weeks past market age, and farmers do hold birds for festive demand.
PROJECTION_HORIZON_DAYS = 21


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SellPoint:
    day: int
    weight_kg: Decimal
    projected_profit: Decimal


@dataclass(frozen=True)
class BatchMetrics:
    """Everything the batch screen and the reports need, computed once."""

    day_in_cycle: int
    cycle_days: int
    alive: int
    deaths: int
    mortality_pct: Decimal

    total_feed_kg: Decimal
    total_cost: Decimal
    cost_per_bird: Decimal
    # The birds the cost is spread across: those still alive while a cycle is
    # running, and those actually sold once it has finished. Dividing a closed
    # cycle by the nought birds left standing would report a cost of zero.
    earning_birds: int

    average_weight_kg: Decimal | None
    # Where that weight came from: "weighed" (a scale), "sold" (the last sale),
    # "estimated" (a growth curve) or "unknown". Feed conversion from a curve
    # is a different claim from feed conversion from a scale.
    weight_source: str
    # What the breed standard says this bird should weigh today, and how the
    # flock compares. Null when the birds have never been weighed.
    target_weight_kg: Decimal | None
    weight_vs_target_pct: Decimal | None
    last_weighed_on: date | None

    feed_conversion: Decimal | None

    projected_revenue: Decimal | None
    projected_profit: Decimal | None
    optimal_sell_day: int | None
    sell_window: list[SellPoint]
    # True when profit peaks inside the window. False means it was still rising
    # at the horizon, and the limit on holding birds is market demand, disease
    # risk and pen space rather than feed cost — which the client should say
    # rather than presenting the last day as an optimum.
    sell_window_peaks: bool

    logged_today: bool
    streak_days: int


def compute(
    batch: Batch, *, on: date | None = None, price_per_kg: Decimal | None = None
) -> BatchMetrics:
    """
    Derive every metric for a batch as at a given date.

    `on` defaults to today. It is a parameter so that reports can restate a
    closed cycle exactly as it stood on the day it ended.
    """
    today = on or date.today()
    price = price_per_kg or DEFAULT_PRICE_PER_KG

    logs = list(batch.logs.filter(logged_on__lte=today).order_by("logged_on"))
    sales = batch.sales.filter(sold_on__lte=today)

    day_in_cycle = max(1, (today - batch.started_on).days + 1)
    cycle_days = batch.bird_type.cycle_days

    deaths = sum(log.deaths for log in logs)
    sold = sales.aggregate(total=Sum("birds"))["total"] or 0
    alive = max(0, batch.stocked - deaths - sold)

    mortality_pct = (
        (Decimal(deaths) / Decimal(batch.stocked) * 100).quantize(Decimal("0.1"))
        if batch.stocked
        else Decimal("0.0")
    )

    total_feed_kg = sum((log.feed_kg for log in logs), Decimal("0"))
    running_cost = sum((log.total_cost for log in logs), Decimal("0"))
    total_cost = _money(batch.chick_cost + running_cost)

    # A finished cycle has no birds left, but it still cost what it cost — so
    # the figures are spread across the birds that were sold.
    earning_birds = sold if (batch.status == Batch.Status.CLOSED and sold) else alive
    cost_per_bird = _money(total_cost / earning_birds) if earning_birds else Decimal("0.00")

    average_weight, weight_source = _average_weight(batch, day_in_cycle)
    target = target_weight_kg(batch, day_in_cycle)
    last_weighing = batch.weighings.order_by("-weighed_on").first()
    # Only worth stating against a weight that was actually measured. Comparing
    # a modelled weight with a published curve compares two models.
    vs_target = (
        (average_weight / target * 100).quantize(Decimal("0.1"))
        if target and average_weight and weight_source in ("weighed", "sold")
        else None
    )
    feed_conversion = None
    if average_weight and earning_birds and day_in_cycle >= FCR_MEANINGFUL_FROM_DAY:
        live_mass = Decimal(earning_birds) * average_weight
        if live_mass > 0:
            feed_conversion = (total_feed_kg / live_mass).quantize(Decimal("0.01"))

    sell_window: list[SellPoint] = []
    projected_revenue = projected_profit = None
    optimal_sell_day = None
    sell_window_peaks = False

    if average_weight and alive:
        projected_revenue = _money(Decimal(alive) * average_weight * price)
        projected_profit = _money(projected_revenue - total_cost)
        sell_window = _project_sell_window(
            batch, alive=alive, from_day=day_in_cycle, total_cost=total_cost, price=price
        )
        if sell_window:
            best = max(sell_window, key=lambda p: p.projected_profit)
            optimal_sell_day = best.day
            sell_window_peaks = best.day < sell_window[-1].day

    logged_days = {log.logged_on for log in logs}
    return BatchMetrics(
        day_in_cycle=day_in_cycle,
        cycle_days=cycle_days,
        alive=alive,
        deaths=deaths,
        mortality_pct=mortality_pct,
        total_feed_kg=total_feed_kg.quantize(Decimal("0.1")),
        total_cost=total_cost,
        cost_per_bird=cost_per_bird,
        earning_birds=earning_birds,
        average_weight_kg=average_weight,
        weight_source=weight_source,
        target_weight_kg=target,
        weight_vs_target_pct=vs_target,
        last_weighed_on=last_weighing.weighed_on if last_weighing else None,
        feed_conversion=feed_conversion,
        projected_revenue=projected_revenue,
        projected_profit=projected_profit,
        optimal_sell_day=optimal_sell_day,
        sell_window=sell_window,
        sell_window_peaks=sell_window_peaks,
        logged_today=today in logged_days,
        streak_days=_streak(logged_days, today),
    )


def _average_weight(batch: Batch, day: int) -> tuple[Decimal | None, str]:
    """
    Live weight per bird, and where the figure came from.

    A bird that has been on a scale beats one that has been modelled, so a
    weighing wins, then a sale, then the growth curve. The source travels with
    the number because feed conversion computed from a curve is a different
    claim from feed conversion computed from a scale, and the farmer is
    entitled to know which one they are reading.
    """
    weighing = batch.weighings.order_by("-weighed_on").first()
    sale = batch.sales.order_by("-sold_on").first()

    # Whichever measurement is more recent. A sale is a weighing of the birds
    # that left; a weighing is of the birds still there.
    if weighing and (not sale or weighing.weighed_on >= sale.sold_on):
        return weighing.average_weight_kg, "weighed"
    if sale:
        return sale.average_weight_kg, "sold"

    if batch.bird_type.code not in ("broiler", "mixed"):
        # Only the broiler curve is characterised. For other birds, weight
        # comes from a scale or it is unknown — better than inventing a number.
        return None, "unknown"

    return _gompertz_weight(day), "estimated"


def target_weight_kg(batch: Batch, day: int) -> Decimal | None:
    """
    What this bird should weigh today, interpolated between published points.

    Returns nothing rather than guessing when the day falls outside the range
    the standard covers.
    """
    points = list(batch.bird_type.weight_standards.order_by("day"))
    if not points:
        return None
    if day <= points[0].day:
        return Decimal(points[0].grams) / 1000
    if day >= points[-1].day:
        return Decimal(points[-1].grams) / 1000

    for lower, upper in pairwise(points):
        if lower.day <= day <= upper.day:
            span = Decimal(upper.day - lower.day)
            progress = Decimal(day - lower.day) / span
            grams = Decimal(lower.grams) + (upper.grams - lower.grams) * progress
            return (grams / 1000).quantize(Decimal("0.01"))
    return None


def _gompertz_weight(day: int) -> Decimal:
    """Live weight at a given day, on a curve that plateaus like a real bird."""
    import math

    exponent = -float(GOMPERTZ_B) * math.exp(-float(GOMPERTZ_K) * day)
    weight = float(GOMPERTZ_MATURE_KG) * math.exp(exponent)
    return Decimal(str(round(weight, 2)))


def _project_sell_window(
    batch: Batch, *, alive: int, from_day: int, total_cost: Decimal, price: Decimal
) -> list[SellPoint]:
    """
    Profit for each day the farmer might sell on.

    Birds keep gaining weight, but they eat to do it. The peak of this curve is
    the day past which waiting costs more than it earns — the single most
    common quiet way to lose money on a cycle.
    """
    if batch.bird_type.code != "broiler":
        return []

    window: list[SellPoint] = []
    horizon = batch.bird_type.cycle_days + PROJECTION_HORIZON_DAYS
    carried = Decimal("0")

    for day in range(max(from_day, 28), horizon + 1):
        weight = _gompertz_weight(day)
        if day > from_day:
            # Every extra day feeds every living bird. Intake scales with the
            # bird's own weight, so this cost grows as the flock does.
            carried += (
                Decimal(alive)
                * weight
                * PROJECTED_DAILY_FEED_RATIO
                * PROJECTED_FEED_PRICE_PER_KG
            )
        revenue = Decimal(alive) * weight * price
        window.append(
            SellPoint(
                day=day,
                weight_kg=weight,
                projected_profit=_money(revenue - total_cost - carried),
            )
        )
    return window


def _streak(logged_days: set[date], today: date) -> int:
    """Consecutive days logged, counting back from today or yesterday."""
    from datetime import timedelta

    if not logged_days:
        return 0
    cursor = today if today in logged_days else today - timedelta(days=1)
    streak = 0
    while cursor in logged_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
