"""
How the farm is doing this week, and this month.

The cycle report answers "did that batch make money", which only lands once the
birds are gone. This answers "how are we doing right now" — the question a
farmer asks on a Sunday evening with birds still in the pen.

Everything is counted from what was actually logged, and compared with the
window before it, because a farmer cannot tell whether 14 deaths is bad without
knowing last week was 3. Where something has not been recorded the report says
so rather than reporting zero: "you spent nothing on feed" is a lie that reads
like a fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from apps.flocks.models import Batch, DailyLog, Sale

KG_PER_BAG = Decimal("25")

# The two windows a farmer actually thinks in.
PERIODS: dict[str, tuple[int, str]] = {
    "week": (7, "This week"),
    "month": (30, "This month"),
}


def _kg(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BatchLine:
    id: str
    name: str
    bird_type: str
    day: int
    birds_alive: int
    deaths: int
    feed_kg: Decimal
    days_logged: int


@dataclass(frozen=True)
class Upcoming:
    batch_name: str
    day: int
    due_on: date
    what: str


@dataclass
class PeriodReport:
    period: str
    label: str
    starts_on: date
    ends_on: date
    days: int

    days_logged: int
    days_possible: int
    active_batches: int
    birds_alive: int

    deaths: int
    deaths_before: int

    feed_kg: Decimal
    feed_bags: Decimal
    feed_before_kg: Decimal

    recorded_spend: Decimal
    revenue: Decimal
    # False when no log in the window carried a feed cost, which is the usual
    # case: the log screen records what the birds ate, not what it cost.
    feed_cost_recorded: bool

    batches: list[BatchLine] = field(default_factory=list)
    upcoming: list[Upcoming] = field(default_factory=list)
    headline: str = ""
    notes: list[str] = field(default_factory=list)


def build(farm_id, *, period: str = "week", on: date | None = None) -> PeriodReport:
    """The farm over the last seven or thirty days, against the window before."""
    days, label = PERIODS.get(period, PERIODS["week"])
    today = on or date.today()
    starts_on = today - timedelta(days=days - 1)
    before_starts = starts_on - timedelta(days=days)

    batches = list(
        Batch.objects.filter(farm_id=farm_id)
        .select_related("bird_type")
        .prefetch_related("bird_type__vaccination_schedule", "bird_type__feed_phases")
    )
    by_id = {b.id: b for b in batches}

    logs = list(
        DailyLog.objects.filter(
            batch__farm_id=farm_id, logged_on__gte=before_starts, logged_on__lte=today
        )
    )
    current = [log for log in logs if log.logged_on >= starts_on]
    before = [log for log in logs if log.logged_on < starts_on]

    deaths = sum(log.deaths for log in current)
    deaths_before = sum(log.deaths for log in before)
    feed_kg = sum((log.feed_kg for log in current), Decimal("0"))
    feed_before = sum((log.feed_kg for log in before), Decimal("0"))
    spend = sum((log.total_cost for log in current), Decimal("0"))
    feed_cost_recorded = any(log.feed_cost > 0 for log in current)

    revenue = sum(
        (
            sale.revenue
            for sale in Sale.objects.filter(
                batch__farm_id=farm_id, sold_on__gte=starts_on, sold_on__lte=today
            )
        ),
        Decimal("0"),
    )

    # Distinct dates carrying any log: the habit, not the row count.
    days_logged = len({log.logged_on for log in current})

    # Only batches that were running during the window belong in the report.
    active = [
        b
        for b in batches
        if b.status == Batch.Status.ACTIVE or any(log.batch_id == b.id for log in current)
    ]

    lines: list[BatchLine] = []
    for batch in sorted(active, key=lambda b: b.started_on, reverse=True):
        mine = [log for log in current if log.batch_id == batch.id]
        all_logs_deaths = sum(
            log.deaths for log in DailyLog.objects.filter(batch=batch, logged_on__lte=today)
        )
        sold = sum(
            sale.birds for sale in Sale.objects.filter(batch=batch, sold_on__lte=today)
        )
        lines.append(
            BatchLine(
                id=str(batch.id),
                name=batch.name,
                bird_type=batch.bird_type.label,
                day=max(1, (today - batch.started_on).days + 1),
                birds_alive=max(0, batch.stocked - all_logs_deaths - sold),
                deaths=sum(log.deaths for log in mine),
                feed_kg=_kg(sum((log.feed_kg for log in mine), Decimal("0"))),
                days_logged=len({log.logged_on for log in mine}),
            )
        )

    birds_alive = sum(line.birds_alive for line in lines)

    upcoming = _upcoming(active, today=today, days=days, by_id=by_id)
    report = PeriodReport(
        period=period,
        label=label,
        starts_on=starts_on,
        ends_on=today,
        days=days,
        days_logged=days_logged,
        days_possible=days,
        active_batches=len(lines),
        birds_alive=birds_alive,
        deaths=deaths,
        deaths_before=deaths_before,
        feed_kg=_kg(feed_kg),
        feed_bags=(feed_kg / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        feed_before_kg=_kg(feed_before),
        recorded_spend=_money(spend),
        revenue=_money(revenue),
        feed_cost_recorded=feed_cost_recorded,
        batches=lines,
        upcoming=upcoming,
    )
    report.headline = _headline(report)
    report.notes = _notes(report, before_any=bool(before))
    return report


def _upcoming(batches, *, today: date, days: int, by_id) -> list[Upcoming]:
    """Doses and feed changes falling in the window ahead, so nothing is a surprise."""
    out: list[Upcoming] = []
    for batch in batches:
        day = max(1, (today - batch.started_on).days + 1)
        for dose in batch.bird_type.vaccination_schedule.all():
            if day < dose.day <= day + days:
                out.append(
                    Upcoming(
                        batch_name=batch.name,
                        day=dose.day,
                        due_on=batch.started_on + timedelta(days=dose.day - 1),
                        what=f"{dose.name} ({dose.route})" if dose.route else dose.name,
                    )
                )
        for phase in batch.bird_type.feed_phases.all():
            if day < phase.day_from <= day + days:
                out.append(
                    Upcoming(
                        batch_name=batch.name,
                        day=phase.day_from,
                        due_on=batch.started_on + timedelta(days=phase.day_from - 1),
                        what=f"Change to {phase.name}",
                    )
                )
    return sorted(out, key=lambda u: u.due_on)


def _headline(r: PeriodReport) -> str:
    """One sentence, in the words a farmer would use."""
    if r.active_batches == 0:
        return "No birds on the farm this period."
    if r.days_logged == 0:
        return (
            f"You did not log any of the last {r.days} days. "
            "Aviro cannot tell you how the farm is doing without them."
        )

    bags = f"{r.feed_bags} bags" if r.feed_bags >= 1 else f"{r.feed_kg} kg"
    if r.deaths == 0:
        return f"You lost no birds and they ate {bags}."

    birds = "bird" if r.deaths == 1 else "birds"
    if r.deaths_before == 0:
        return f"You lost {r.deaths} {birds} and they ate {bags}."
    if r.deaths < r.deaths_before:
        return (
            f"You lost {r.deaths} {birds} — better than {r.deaths_before} "
            f"the period before. They ate {bags}."
        )
    if r.deaths > r.deaths_before:
        return (
            f"You lost {r.deaths} {birds} — up from {r.deaths_before} "
            f"the period before. They ate {bags}."
        )
    return f"You lost {r.deaths} {birds}, the same as last period. They ate {bags}."


def _notes(r: PeriodReport, *, before_any: bool) -> list[str]:
    notes: list[str] = []

    if r.active_batches and r.days_logged < r.days_possible:
        missed = r.days_possible - r.days_logged
        notes.append(
            f"{missed} of {r.days_possible} days were not logged. "
            "Days with no entry are counted as no feed and no deaths, which "
            "makes the figures above look better than the farm really did."
        )

    if r.feed_kg > 0 and not r.feed_cost_recorded:
        notes.append(
            "No feed cost was recorded, so the spending below covers medicine "
            "and other costs only."
        )

    if not before_any and r.deaths:
        notes.append("There is nothing to compare with yet. Next period will have a trend.")

    return notes
