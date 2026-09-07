"""
What today should look like for one batch.

The cycle plan answers "what will this take?" before the birds arrive. This
answers the same question narrowed to one day, at the moment the farmer is
standing in the pen with the app open: how much feed is about right for the
birds still alive, whether a dose is due, and how many deaths would be worth a
second look.

It is deliberately advisory. A novice does not need the app to refuse their
number — they need to know the number they were about to enter is half of what
the birds should be eating, while they can still do something about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..models import Batch, FeedPhase
from .plan import CAVEAT, KG_PER_BAG

# Real intake moves with heat, feed quality and wastage, so the band has to be
# wide enough that an ordinary day never nags. These bounds are set to catch
# the mistakes that actually cost money — a bag miscounted, a unit confused —
# not natural variation.
LOW_RATIO = Decimal("0.75")
HIGH_RATIO = Decimal("1.25")

# A day's deaths worth a second look: half a percent of the living flock, and
# never fewer than three. Small flocks would otherwise raise a question every
# time one bird died, which teaches farmers to ignore the app.
DEATHS_WATCH_RATIO = Decimal("0.005")
DEATHS_WATCH_FLOOR = 3

# How far ahead a dose is worth mentioning while the farmer is already logging.
SOON_DAYS = 3


def _kg(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DueDose:
    day: int
    due_on: date
    name: str
    route: str
    notes: str


@dataclass(frozen=True)
class DayGuidance:
    on: date
    day: int
    birds_alive: int

    # Feed. None once the birds are past the end of the programme, which is
    # normal for a layer in lay or a broiler held back for a buyer.
    phase_name: str | None
    grams_per_bird: int | None
    expected_kg: Decimal | None
    expected_bags: Decimal | None
    low_kg: Decimal | None
    high_kg: Decimal | None

    # The next feed change, so nobody is surprised by it on the day.
    next_phase_name: str | None
    next_phase_starts_on: date | None
    days_until_change: int | None

    due_today: list[DueDose]
    due_soon: list[DueDose]

    deaths_watch_from: int
    caveat: str = CAVEAT


def _phase_for(phases: list[FeedPhase], day: int) -> FeedPhase | None:
    for phase in phases:
        if phase.day_from <= day <= phase.day_to:
            return phase
    return None


def build(batch: Batch, *, alive: int, on: date | None = None) -> DayGuidance:
    """Guidance for one batch on one day, for the birds still standing."""
    today = on or date.today()
    day = max(1, (today - batch.started_on).days + 1)
    birds = Decimal(alive)

    phases = list(batch.bird_type.feed_phases.all())
    phase = _phase_for(phases, day)

    grams = expected = bags = low = high = None
    if phase is not None:
        grams_dec = phase.grams_on(day)
        grams = int(grams_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        kg = grams_dec * birds / 1000
        expected = _kg(kg)
        bags = (kg / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        low = _kg(kg * LOW_RATIO)
        high = _kg(kg * HIGH_RATIO)

    # The next phase by start day, whether or not the birds are in one now.
    upcoming = [p for p in phases if p.day_from > day]
    next_phase = min(upcoming, key=lambda p: p.day_from) if upcoming else None
    next_name = next_phase.name if next_phase else None
    next_starts = (
        batch.started_on + timedelta(days=next_phase.day_from - 1) if next_phase else None
    )
    until_change = next_phase.day_from - day if next_phase else None

    due_today: list[DueDose] = []
    due_soon: list[DueDose] = []
    for dose in batch.bird_type.vaccination_schedule.all():
        gap = dose.day - day
        if gap != 0 and not (0 < gap <= SOON_DAYS):
            continue
        entry = DueDose(
            day=dose.day,
            due_on=batch.started_on + timedelta(days=dose.day - 1),
            name=dose.name,
            route=dose.route,
            notes=dose.notes,
        )
        (due_today if gap == 0 else due_soon).append(entry)

    watch = max(
        DEATHS_WATCH_FLOOR,
        int((birds * DEATHS_WATCH_RATIO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
    )

    return DayGuidance(
        on=today,
        day=day,
        birds_alive=alive,
        phase_name=phase.name if phase else None,
        grams_per_bird=grams,
        expected_kg=expected,
        expected_bags=bags,
        low_kg=low,
        high_kg=high,
        next_phase_name=next_name,
        next_phase_starts_on=next_starts,
        days_until_change=until_change,
        due_today=due_today,
        due_soon=due_soon,
        deaths_watch_from=watch,
    )
