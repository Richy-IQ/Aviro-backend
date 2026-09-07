"""
A cooperative's view of its farms.

The question an officer actually has is not "how is the network doing" but
"which of my members is in trouble this week, and which has stopped telling me
anything". Both are answered here, and the second matters as much as the first:
a farm that goes quiet is usually a farm where something went wrong.

Deliberately read-only and deliberately shallow. The officer sees enough to
know who to call. The farm's own records stay the farmer's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Max, Sum

from apps.farms.models import Farm, Organisation
from apps.flocks.models import Batch, DailyLog, Sale, Weighing
from apps.flocks.services.metrics import target_weight_kg

KG_PER_BAG = Decimal("25")

PERIODS: dict[str, tuple[int, str]] = {
    "week": (7, "This week"),
    "month": (30, "This month"),
}

# A farm with birds that has not logged for this many days has effectively
# stopped reporting, whatever the reason.
SILENT_AFTER_DAYS = 3

# Deaths in the window as a share of the birds that were there, above which an
# officer should be calling rather than reading.
MORTALITY_CONCERN_PCT = Decimal("3")

# Below this share of the breed target, the birds are behind enough to matter.
BEHIND_TARGET_PCT = Decimal("85")


def _kg(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FarmRow:
    id: str
    name: str
    location: str

    active_batches: int
    birds_alive: int

    days_logged: int
    days_possible: int
    last_logged_on: date | None
    days_silent: int | None

    deaths: int
    deaths_before: int
    feed_kg: Decimal
    weight_vs_target_pct: Decimal | None

    status: str
    attention: list[str]


@dataclass
class NetworkOverview:
    organisation_name: str
    period: str
    label: str
    starts_on: date
    ends_on: date
    days: int

    farm_count: int
    farms_with_birds: int
    farms_logging: int
    # The number that decides whether any of this is worth anything: records
    # with holes cannot be lent against, sold on, or learned from.
    logging_rate_pct: Decimal

    birds_alive: int
    deaths: int
    deaths_before: int
    feed_kg: Decimal
    feed_bags: Decimal

    rows: list[FarmRow] = field(default_factory=list)
    needs_attention: list[FarmRow] = field(default_factory=list)
    headline: str = ""


# Worst first. An officer with ten minutes should spend them at the top.
STATUS_ORDER = {"losing": 0, "silent": 1, "behind": 2, "fine": 3, "idle": 4}


def build(organisation: Organisation, *, period: str = "week", on: date | None = None):
    days, label = PERIODS.get(period, PERIODS["week"])
    today = on or date.today()
    starts_on = today - timedelta(days=days - 1)
    before_starts = starts_on - timedelta(days=days)

    farms = list(Farm.objects.filter(organisation=organisation).order_by("name"))
    if not farms:
        return NetworkOverview(
            organisation_name=organisation.name,
            period=period,
            label=label,
            starts_on=starts_on,
            ends_on=today,
            days=days,
            farm_count=0,
            farms_with_birds=0,
            farms_logging=0,
            logging_rate_pct=Decimal("0.0"),
            birds_alive=0,
            deaths=0,
            deaths_before=0,
            feed_kg=Decimal("0.0"),
            feed_bags=Decimal("0.0"),
            headline="No farms have joined yet.",
        )

    batches = list(
        Batch.objects.filter(farm__in=farms, status=Batch.Status.ACTIVE)
        .select_related("bird_type", "farm")
        .prefetch_related("bird_type__weight_standards")
    )
    batch_ids = [b.id for b in batches]

    # Bulk rather than per-farm: a cooperative pilot is fifty farms, and this
    # view is the one an officer refreshes.
    all_deaths = {
        row["batch"]: row["n"]
        for row in DailyLog.objects.filter(batch_id__in=batch_ids)
        .values("batch")
        .annotate(n=Sum("deaths"))
    }
    all_sold = {
        row["batch"]: row["n"]
        for row in Sale.objects.filter(batch_id__in=batch_ids)
        .values("batch")
        .annotate(n=Sum("birds"))
    }

    window_logs = list(
        DailyLog.objects.filter(
            batch__farm__in=farms, logged_on__gte=before_starts, logged_on__lte=today
        ).select_related("batch")
    )
    last_log = {
        row["batch__farm"]: row["last"]
        for row in DailyLog.objects.filter(batch__farm__in=farms)
        .values("batch__farm")
        .annotate(last=Max("logged_on"))
    }
    latest_weighing: dict = {}
    for w in Weighing.objects.filter(batch_id__in=batch_ids).order_by("batch", "-weighed_on"):
        latest_weighing.setdefault(w.batch_id, w)

    rows = [
        _row(
            farm,
            batches=[b for b in batches if b.farm_id == farm.id],
            logs=[log for log in window_logs if log.batch.farm_id == farm.id],
            starts_on=starts_on,
            today=today,
            days=days,
            all_deaths=all_deaths,
            all_sold=all_sold,
            last_logged_on=last_log.get(farm.id),
            latest_weighing=latest_weighing,
        )
        for farm in farms
    ]

    with_birds = [r for r in rows if r.active_batches]
    logging = [r for r in with_birds if r.days_logged > 0]
    deaths = sum(r.deaths for r in rows)
    deaths_before = sum(r.deaths_before for r in rows)
    feed = sum((r.feed_kg for r in rows), Decimal("0"))

    overview = NetworkOverview(
        organisation_name=organisation.name,
        period=period,
        label=label,
        starts_on=starts_on,
        ends_on=today,
        days=days,
        farm_count=len(rows),
        farms_with_birds=len(with_birds),
        farms_logging=len(logging),
        logging_rate_pct=(
            (Decimal(len(logging)) / Decimal(len(with_birds)) * 100).quantize(Decimal("0.1"))
            if with_birds
            else Decimal("0.0")
        ),
        birds_alive=sum(r.birds_alive for r in rows),
        deaths=deaths,
        deaths_before=deaths_before,
        feed_kg=_kg(feed),
        feed_bags=(feed / KG_PER_BAG).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        rows=sorted(rows, key=lambda r: (STATUS_ORDER[r.status], r.name)),
    )
    overview.needs_attention = [r for r in overview.rows if r.attention]
    overview.headline = _headline(overview)
    return overview



def _row(
    farm: Farm,
    *,
    batches,
    logs,
    starts_on: date,
    today: date,
    days: int,
    all_deaths,
    all_sold,
    last_logged_on,
    latest_weighing,
) -> FarmRow:
    current = [log for log in logs if log.logged_on >= starts_on]
    before = [log for log in logs if log.logged_on < starts_on]

    alive = 0
    for batch in batches:
        alive += max(
            0, batch.stocked - all_deaths.get(batch.id, 0) - all_sold.get(batch.id, 0)
        )

    deaths = sum(log.deaths for log in current)
    deaths_before = sum(log.deaths for log in before)
    feed = sum((log.feed_kg for log in current), Decimal("0"))
    days_logged = len({log.logged_on for log in current})
    days_silent = (today - last_logged_on).days if last_logged_on else None

    # Weight against the breed target, from the most recent flock that has
    # actually been on a scale.
    vs_target = None
    for batch in batches:
        weighing = latest_weighing.get(batch.id)
        if not weighing:
            continue
        day = max(1, (today - batch.started_on).days + 1)
        target = target_weight_kg(batch, day)
        if target:
            vs_target = (weighing.average_weight_kg / target * 100).quantize(Decimal("0.1"))
            break

    attention: list[str] = []
    status = "fine"

    if not batches:
        status = "idle"
    else:
        # Deaths as a share of the birds that were standing at the start.
        exposed = alive + deaths
        rate = (Decimal(deaths) / Decimal(exposed) * 100) if exposed else Decimal("0")

        if rate > MORTALITY_CONCERN_PCT:
            status = "losing"
            attention.append(
                f"Lost {deaths} birds in {days} days — "
                f"{rate.quantize(Decimal('0.1'))}% of the flock."
            )
        elif days_silent is None or days_silent >= SILENT_AFTER_DAYS:
            status = "silent"
            attention.append(
                "Has birds but has never logged."
                if days_silent is None
                else f"Has not logged for {days_silent} days."
            )
        elif vs_target is not None and vs_target < BEHIND_TARGET_PCT:
            status = "behind"
            attention.append(f"Birds at {vs_target}% of target weight.")

    return FarmRow(
        id=str(farm.id),
        name=farm.name,
        location=farm.location,
        active_batches=len(batches),
        birds_alive=alive,
        days_logged=days_logged,
        days_possible=days,
        last_logged_on=last_logged_on,
        days_silent=days_silent,
        deaths=deaths,
        deaths_before=deaths_before,
        feed_kg=_kg(feed),
        weight_vs_target_pct=vs_target,
        status=status,
        attention=attention,
    )


def _headline(o: NetworkOverview) -> str:
    if o.farms_with_birds == 0:
        return f"{o.farm_count} farms, none with birds in the pen right now."

    needing = len(o.needs_attention)
    reporting = (
        f"{o.farms_logging} of {o.farms_with_birds} farms with birds reported this period"
    )
    if needing == 0:
        return f"{reporting}. Nothing needs your attention."
    return f"{reporting}. {needing} {'farm needs' if needing == 1 else 'farms need'} a call."
