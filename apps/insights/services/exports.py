"""
Farm records as CSV.

A farmer who wants their numbers in a spreadsheet, or a lender who wants the
rows behind a statement, should be able to take them out. The export is
deliberately raw: one line per record, as recorded, with nothing derived. A
figure someone can recompute themselves is worth more than one they must trust.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from apps.farms.models import Farm
from apps.flocks.models import DailyLog, Sale

DATASETS = ("logs", "sales")


def _writer() -> tuple[io.StringIO, csv.writer]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer)


def daily_logs(farm: Farm, *, starts_on: date, ends_on: date) -> str:
    buffer, out = _writer()
    out.writerow(
        [
            "Date",
            "Batch",
            "Bird type",
            "Day of cycle",
            "Feed (kg)",
            "Deaths",
            "Cause",
            "Health activity",
            "Feed cost",
            "Medication cost",
            "Other cost",
            "Note",
        ]
    )
    rows = (
        DailyLog.objects.filter(
            batch__farm=farm, logged_on__gte=starts_on, logged_on__lte=ends_on
        )
        .select_related("batch", "batch__bird_type")
        .order_by("logged_on", "batch__name")
    )
    for log in rows:
        out.writerow(
            [
                log.logged_on.isoformat(),
                log.batch.name,
                log.batch.bird_type.label,
                log.day_in_cycle,
                log.feed_kg,
                log.deaths,
                log.get_death_cause_display() if log.death_cause else "",
                log.get_health_activity_display(),
                log.feed_cost,
                log.meds_cost,
                log.other_cost,
                log.note,
            ]
        )
    return buffer.getvalue()


def sales(farm: Farm, *, starts_on: date, ends_on: date) -> str:
    buffer, out = _writer()
    out.writerow(
        [
            "Date",
            "Batch",
            "Bird type",
            "Kind",
            "Birds",
            "Average weight (kg)",
            "Total weight (kg)",
            "Revenue",
            "Price per kg",
            "Buyer type",
            "Buyer",
            "Note",
        ]
    )
    rows = (
        Sale.objects.filter(batch__farm=farm, sold_on__gte=starts_on, sold_on__lte=ends_on)
        .select_related("batch", "batch__bird_type")
        .order_by("sold_on", "batch__name")
    )
    for sale in rows:
        price = sale.price_per_kg
        out.writerow(
            [
                sale.sold_on.isoformat(),
                sale.batch.name,
                sale.batch.bird_type.label,
                sale.get_kind_display(),
                sale.birds,
                sale.average_weight_kg,
                sale.birds * sale.average_weight_kg,
                sale.revenue,
                round(price, 2) if price is not None else "",
                sale.get_buyer_type_display() if sale.buyer_type else "",
                sale.buyer_name,
                sale.note,
            ]
        )
    return buffer.getvalue()


def build(farm: Farm, *, dataset: str, starts_on: date, ends_on: date) -> tuple[str, str]:
    """Returns the CSV body and the filename it should be saved as."""
    maker = sales if dataset == "sales" else daily_logs
    body = maker(farm, starts_on=starts_on, ends_on=ends_on)
    slug = "".join(c if c.isalnum() else "-" for c in farm.name).strip("-").lower()
    name = f"{slug}-{dataset}-{starts_on.isoformat()}-to-{ends_on.isoformat()}.csv"
    return body, name
