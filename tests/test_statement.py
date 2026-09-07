"""
The income statement a farmer takes to a bank.

The figures have to be defensible, and just as importantly the statement has to
be honest about what it does not know. A statement that hides a missing feed
cost is worse than no statement — it overstates profit on the face of it.
"""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import DailyLog, Sale
from apps.insights.services import exports as export_service
from apps.insights.services import statement as statement_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def window():
    today = date.today()
    return today - timedelta(days=30), today


def test_revenue_is_what_was_actually_sold(batch, farm, window):
    Sale.objects.create(
        batch=batch,
        sold_on=date.today() - timedelta(days=2),
        birds=300,
        average_weight_kg=Decimal("2.40"),
        revenue=Decimal("1440000.00"),
        buyer_type="wholesaler",
    )
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    assert s.revenue == Decimal("1440000.00")
    assert s.birds_sold == 300
    assert s.price_per_kg == Decimal("2000.00")


def test_a_sale_outside_the_period_is_not_counted(batch, farm):
    Sale.objects.create(
        batch=batch,
        sold_on=date.today() - timedelta(days=200),
        birds=100,
        average_weight_kg=Decimal("2.00"),
        revenue=Decimal("400000.00"),
    )
    s = statement_service.build(
        farm, starts_on=date.today() - timedelta(days=30), ends_on=date.today()
    )
    assert s.revenue == Decimal("0.00")


def test_missing_feed_cost_is_declared_on_the_face_of_the_statement(batch, farm, window):
    """The failure mode that would embarrass a farmer in a bank."""
    Sale.objects.create(
        batch=batch,
        sold_on=date.today() - timedelta(days=1),
        birds=100,
        average_weight_kg=Decimal("2.00"),
        revenue=Decimal("400000.00"),
    )
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    assert s.feed_cost_recorded is False
    assert any("feed" in note.lower() and "overstated" in note.lower() for note in s.limitations)
    assert not any(line.label == "Feed" for line in s.cost_lines)


def test_recorded_feed_appears_as_a_cost_line(batch, farm, window):
    DailyLog.objects.create(
        batch=batch,
        logged_on=date.today() - timedelta(days=3),
        feed_kg=Decimal("500"),
        feed_cost=Decimal("360000.00"),
    )
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    feed = next(line for line in s.cost_lines if line.label == "Feed")
    assert feed.amount == Decimal("360000.00")
    assert s.feed_cost_recorded is True


def test_chicks_are_a_cost_of_the_period_they_were_bought_in(batch, farm, window):
    """The batch fixture was stocked 20 days ago at 850 a bird."""
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    chicks = next(line for line in s.cost_lines if line.label == "Day-old chicks")
    assert chicks.amount == Decimal("425000.00")

    # A window that closes before the batch was stocked must not carry its cost.
    earlier = statement_service.build(
        farm,
        starts_on=date.today() - timedelta(days=60),
        ends_on=date.today() - timedelta(days=40),
    )
    assert not any(line.label == "Day-old chicks" for line in earlier.cost_lines)


def test_gross_profit_is_revenue_less_the_lines_shown(batch, farm, window):
    """A statement whose total does not follow from its own rows is not evidence."""
    Sale.objects.create(
        batch=batch,
        sold_on=date.today() - timedelta(days=1),
        birds=400,
        average_weight_kg=Decimal("2.30"),
        revenue=Decimal("1800000.00"),
    )
    DailyLog.objects.create(
        batch=batch,
        logged_on=date.today() - timedelta(days=5),
        feed_kg=Decimal("400"),
        feed_cost=Decimal("288000.00"),
        meds_cost=Decimal("15000.00"),
    )
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    assert sum(line.amount for line in s.cost_lines) == s.total_cost
    assert s.gross_profit == s.revenue - s.total_cost
    assert s.profit_per_bird == (s.gross_profit / 400).quantize(Decimal("0.01"))


def test_incomplete_records_are_stated_not_hidden(batch, farm, window):
    DailyLog.objects.create(
        batch=batch, logged_on=date.today(), feed_kg=Decimal("10"), feed_cost=Decimal("7200")
    )
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)

    assert s.days_logged == 1
    assert s.days_in_period == 31
    assert any("30 days were not recorded" in note for note in s.limitations)


def test_the_basis_of_preparation_is_always_stated(batch, farm, window):
    starts_on, ends_on = window
    s = statement_service.build(farm, starts_on=starts_on, ends_on=ends_on)
    assert any("cash basis" in b for b in s.basis)
    assert any("not been audited" in b for b in s.basis)


def test_named_windows_line_up_with_the_calendar():
    today = date(2026, 3, 17)
    assert statement_service.month_to_date(today) == (date(2026, 3, 1), today)
    assert statement_service.last_full_month(today) == (date(2026, 2, 1), date(2026, 2, 28))
    assert statement_service.year_to_date(today) == (date(2026, 1, 1), today)


def test_the_export_gives_back_the_rows_themselves(batch, farm, window):
    DailyLog.objects.create(
        batch=batch,
        logged_on=date.today() - timedelta(days=1),
        feed_kg=Decimal("25"),
        deaths=2,
        feed_cost=Decimal("18000"),
    )
    starts_on, ends_on = window
    body, filename = export_service.build(
        farm, dataset="logs", starts_on=starts_on, ends_on=ends_on
    )

    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][0] == "Date"
    assert len(rows) == 2
    assert rows[1][1] == batch.name
    assert rows[1][5] == "2"
    assert filename.endswith(".csv")
    assert starts_on.isoformat() in filename
