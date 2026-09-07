"""
The cycle plan.

Answers the question a first-time farmer actually has when they buy 500 chicks:
how much feed do I need, when do I change it, when do I vaccinate, and what
will it cost me. Built from the bird type's own feeding programme and
vaccination schedule, so a layer keeper never gets a broiler's answers.

Everything here is a projection from published guide figures. Real intake moves
with temperature, feed quality and management, so the plan is something to
weigh against the birds rather than a promise — which is what the caveat
returned alongside it says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..models import BirdType

# Feed is sold in 25kg bags across Nigerian markets, so quantities are stated
# in bags as well as kilograms — that is the unit a farmer actually buys in.
KG_PER_BAG = Decimal("25")

# Used when no local price is known. Overridden by the caller wherever a real
# market figure is available.
DEFAULT_FEED_PRICE_PER_KG = Decimal("720")


def _kg(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PhasePlan:
    name: str
    day_from: int
    day_to: int
    starts_on: date
    ends_on: date
    days: int
    grams_per_bird_start: int
    grams_per_bird_end: int
    total_kg: Decimal
    bags: Decimal
    estimated_cost: Decimal
    notes: str


@dataclass(frozen=True)
class WeekPlan:
    week: int
    day_from: int
    day_to: int
    starts_on: date
    feed_name: str
    total_kg: Decimal
    bags: Decimal


@dataclass(frozen=True)
class PlannedVaccination:
    day: int
    due_on: date
    name: str
    route: str
    notes: str


@dataclass
class CyclePlan:
    bird_type: str
    bird_type_label: str
    stocked: int
    started_on: date
    ends_on: date
    cycle_days: int
    cycle_goal: str

    phases: list[PhasePlan]
    weeks: list[WeekPlan]
    vaccinations: list[PlannedVaccination]

    total_feed_kg: Decimal
    total_bags: Decimal
    feed_per_bird_kg: Decimal
    estimated_feed_cost: Decimal
    estimated_chick_cost: Decimal
    estimated_total_cost: Decimal
    estimated_cost_per_bird: Decimal
    feed_price_per_kg: Decimal

    caveat: str = field(default="")


CAVEAT = (
    "These quantities are a guide from published breed figures, not a promise. "
    "Real intake changes with heat, feed quality and how the birds are managed, "
    "so weigh what you actually use against this and trust the birds over the table."
)


def build(
    bird_type: BirdType,
    *,
    stocked: int,
    started_on: date,
    cost_per_bird: Decimal | None = None,
    feed_price_per_kg: Decimal | None = None,
) -> CyclePlan:
    """Project a whole cycle for this many birds of this type, from this date."""
    price = feed_price_per_kg or DEFAULT_FEED_PRICE_PER_KG
    birds = Decimal(stocked)

    phases: list[PhasePlan] = []
    daily_kg: dict[int, tuple[Decimal, str]] = {}

    for phase in bird_type.feed_phases.all():
        phase_kg = Decimal("0")
        for day in range(phase.day_from, phase.day_to + 1):
            grams = phase.grams_on(day)
            kg = grams * birds / 1000
            daily_kg[day] = (kg, phase.name)
            phase_kg += kg

        phases.append(
            PhasePlan(
                name=phase.name,
                day_from=phase.day_from,
                day_to=phase.day_to,
                starts_on=started_on + timedelta(days=phase.day_from - 1),
                ends_on=started_on + timedelta(days=phase.day_to - 1),
                days=phase.days,
                grams_per_bird_start=phase.grams_per_bird_start,
                grams_per_bird_end=phase.grams_per_bird_end,
                total_kg=_kg(phase_kg),
                bags=(phase_kg / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                estimated_cost=_money(phase_kg * price),
                notes=phase.notes,
            )
        )

    # Weekly rows, because feed is bought weekly rather than daily.
    weeks: list[WeekPlan] = []
    if daily_kg:
        last_day = max(daily_kg)
        for week_start in range(1, last_day + 1, 7):
            week_end = min(week_start + 6, last_day)
            week_kg = sum((daily_kg[d][0] for d in range(week_start, week_end + 1)), Decimal("0"))
            weeks.append(
                WeekPlan(
                    week=(week_start - 1) // 7 + 1,
                    day_from=week_start,
                    day_to=week_end,
                    starts_on=started_on + timedelta(days=week_start - 1),
                    # The feed in use on the first day of the week.
                    feed_name=daily_kg[week_start][1],
                    total_kg=_kg(week_kg),
                    # Rounded up: you cannot buy nine tenths of a bag.
                    bags=(week_kg / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                )
            )

    vaccinations = [
        PlannedVaccination(
            day=dose.day,
            due_on=started_on + timedelta(days=dose.day - 1),
            name=dose.name,
            route=dose.route,
            notes=dose.notes,
        )
        for dose in bird_type.vaccination_schedule.all()
    ]

    total_kg = sum((kg for kg, _ in daily_kg.values()), Decimal("0"))
    feed_cost = _money(total_kg * price)
    chick_cost = _money(birds * cost_per_bird) if cost_per_bird else Decimal("0.00")
    total_cost = _money(feed_cost + chick_cost)

    return CyclePlan(
        bird_type=bird_type.code,
        bird_type_label=bird_type.label,
        stocked=stocked,
        started_on=started_on,
        ends_on=started_on + timedelta(days=bird_type.cycle_days - 1),
        cycle_days=bird_type.cycle_days,
        cycle_goal=bird_type.cycle_goal,
        phases=phases,
        weeks=weeks,
        vaccinations=vaccinations,
        total_feed_kg=_kg(total_kg),
        total_bags=(total_kg / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        feed_per_bird_kg=(total_kg / birds).quantize(Decimal("0.01")) if birds else Decimal("0"),
        estimated_feed_cost=feed_cost,
        estimated_chick_cost=chick_cost,
        estimated_total_cost=total_cost,
        estimated_cost_per_bird=_money(total_cost / birds) if birds else Decimal("0.00"),
        feed_price_per_kg=price,
        caveat=CAVEAT,
    )
