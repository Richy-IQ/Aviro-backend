"""
Alerts.

Derived from the state of a batch, not stored. An alert that lives in a table
goes stale the moment the farmer fixes the thing it warned about; deriving them
means the list is always true right now.

Each alert says what happened, what it probably means, and what to do — in that
order, because a farmer reading it at dusk needs the action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.flocks.models import Batch, DailyLog
from apps.flocks.services import metrics as metrics_service

# A day's deaths above this multiple of the recent average is worth flagging.
SPIKE_MULTIPLE = 3
MORTALITY_CONCERN_PCT = 7
FCR_CONCERN = 1.8

# No bird converts feed to meat better than about 1:1. A ratio under this means
# the recorded weight or the recorded feed is wrong — almost always a mistyped
# weight — and silently showing it would tell a farmer they are doing
# brilliantly when their records are broken.
FCR_IMPLAUSIBLE_BELOW = 1.0


@dataclass(frozen=True)
class Alert:
    id: str
    kind: str  # error | warn | success | info
    title: str
    body: str
    action: str
    batch_id: str | None = None
    batch_name: str | None = None


def for_batch(batch: Batch) -> list[Alert]:
    m = metrics_service.compute(batch)
    alerts: list[Alert] = []

    spike = _mortality_spike(batch)
    if spike:
        alerts.append(spike)

    if m.mortality_pct > MORTALITY_CONCERN_PCT:
        alerts.append(
            Alert(
                id="mortality-high",
                kind="error",
                title=f"Losses in {batch.name} are above what is normal",
                body=(
                    f"{m.deaths} of {batch.stocked} birds have died — {m.mortality_pct}%. "
                    f"Under 5% across a cycle is healthy."
                ),
                action="Speak to a vet about what is driving it.",
                batch_id=str(batch.id),
                batch_name=batch.name,
            )
        )

    if m.feed_conversion and float(m.feed_conversion) < FCR_IMPLAUSIBLE_BELOW:
        alerts.append(
            Alert(
                id="fcr-implausible",
                kind="warn",
                title="These numbers do not add up",
                body=(
                    f"{batch.name} shows {m.feed_conversion}kg of feed for each kilogram of "
                    f"bird. No bird converts feed better than about 1 to 1, so either the "
                    f"weight or the feed recorded is wrong."
                ),
                action="Check the weight you entered on your last sale.",
                batch_id=str(batch.id),
                batch_name=batch.name,
            )
        )
    elif m.feed_conversion and float(m.feed_conversion) > FCR_CONCERN:
        alerts.append(
            Alert(
                id="fcr-drifting",
                kind="warn",
                title="Feed is not converting well",
                body=(
                    f"You are using {m.feed_conversion}kg of feed for each kilogram of bird. "
                    f"Under 1.7 is good."
                ),
                action="Check feed quality, water flow and whether the birds are healthy.",
                batch_id=str(batch.id),
                batch_name=batch.name,
            )
        )

    due = _vaccination_due(batch, m.day_in_cycle)
    if due:
        alerts.append(due)

    if m.optimal_sell_day and m.day_in_cycle >= m.optimal_sell_day - 5:
        alerts.append(
            Alert(
                id="sell-window",
                kind="success",
                title="The best day to sell is close",
                body=(
                    f"Profit on {batch.name} peaks around day {m.optimal_sell_day}. "
                    f"Every day after that costs more in feed than it adds in weight."
                ),
                action="Line up your buyers now.",
                batch_id=str(batch.id),
                batch_name=batch.name,
            )
        )

    if not m.logged_today and m.day_in_cycle > 1:
        alerts.append(
            Alert(
                id="not-logged",
                kind="info",
                title=f"{batch.name} is not logged for today",
                body="Two minutes now keeps your numbers honest.",
                action="Log today",
                batch_id=str(batch.id),
                batch_name=batch.name,
            )
        )

    return alerts


def _mortality_spike(batch: Batch) -> Alert | None:
    """A sudden jump against the batch's own recent baseline, not a fixed number."""
    recent = list(
        DailyLog.objects.filter(
            batch=batch, logged_on__gte=timezone.localdate() - timedelta(days=7)
        ).order_by("-logged_on")
    )
    if len(recent) < 3:
        return None

    latest, *earlier = recent
    baseline = sum(log.deaths for log in earlier) / len(earlier)
    if baseline <= 0 or latest.deaths < max(3, baseline * SPIKE_MULTIPLE):
        return None

    return Alert(
        id="mortality-spike",
        kind="error",
        title=f"Higher than usual deaths in {batch.name}",
        body=(
            f"{latest.deaths} birds died on {latest.logged_on:%-d %B}, against about "
            f"{baseline:.0f} a day recently. That is roughly "
            f"{latest.deaths / baseline:.0f} times normal."
        ),
        action="Call a vet today rather than waiting to see if it passes.",
        batch_id=str(batch.id),
        batch_name=batch.name,
    )


def _vaccination_due(batch: Batch, day: int) -> Alert | None:
    schedule = batch.bird_type.vaccination_schedule.filter(day__gte=day, day__lte=day + 3)
    dose = schedule.order_by("day").first()
    if dose is None:
        return None

    when = "today" if dose.day == day else f"in {dose.day - day} days"
    return Alert(
        id=f"vaccination-{dose.day}",
        kind="warn",
        title=f"{dose.name} is due {when}",
        body=f"Given by {dose.route.lower()}. {dose.notes}".strip(),
        action="Buy the vaccine now" if dose.day > day else "Give it before the day ends",
        batch_id=str(batch.id),
        batch_name=batch.name,
    )
