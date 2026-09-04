"""
Cycle reports.

A farmer takes this to a cooperative or a lender, so the arithmetic has to add
up and an unfinished cycle must never read as money received.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import Batch, Sale
from apps.flocks.services import metrics as metrics_service
from apps.insights.services import reports as report_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def closed_batch(logged_batch) -> Batch:
    """The logged batch, sold in full on day 21."""
    sold_on = logged_batch.started_on + timedelta(days=20)
    Sale.objects.create(
        batch=logged_batch,
        sold_on=sold_on,
        kind=Sale.Kind.FULL,
        birds=475,
        average_weight_kg=Decimal("2.40"),
        revenue=Decimal("3648000"),
    )
    logged_batch.status = Batch.Status.CLOSED
    logged_batch.closed_on = sold_on
    logged_batch.save(update_fields=["status", "closed_on"])
    return logged_batch


def test_revenue_less_cost_of_production_equals_gross_profit(closed_batch):
    r = report_service.build(closed_batch)
    assert r.revenue - r.total_cost == r.gross_profit


def test_the_cost_lines_sum_to_the_total(closed_batch):
    """
    If the breakdown does not add up to the total, the farmer is being shown a
    document they cannot defend.
    """
    r = report_service.build(closed_batch)
    assert sum(line.amount for line in r.costs) == r.total_cost


def test_cost_lines_are_stated_as_a_share_of_revenue(closed_batch):
    r = report_service.build(closed_batch)
    feed = next(line for line in r.costs if line.category == "Feed")
    expected = (feed.amount / r.revenue * 100).quantize(Decimal("0.1"))
    assert feed.pct_of_revenue == expected


def test_a_closed_cycle_is_stated_on_money_received(closed_batch):
    """Not on what the birds might have fetched — they are already sold."""
    r = report_service.build(closed_batch)
    assert r.is_closed is True
    assert r.revenue == Decimal("3648000.00")
    assert r.sold == 475


def test_an_open_cycle_is_a_projection_and_says_so(logged_batch):
    r = report_service.build(logged_batch)
    assert r.is_closed is False
    assert any("projection" in note for note in r.insights)


def test_unit_economics_divide_by_the_birds_that_earned_the_money(closed_batch):
    r = report_service.build(closed_batch)
    assert r.cost_per_bird == (r.total_cost / r.sold).quantize(Decimal("0.01"))
    assert r.revenue_per_bird == (r.revenue / r.sold).quantize(Decimal("0.01"))
    # The three per-bird figures must be internally consistent.
    assert r.revenue_per_bird - r.cost_per_bird == pytest.approx(
        r.profit_per_bird, abs=Decimal("0.01")
    )


def test_cost_per_kg_uses_the_weight_actually_sold(closed_batch):
    r = report_service.build(closed_batch)
    total_kg = Decimal(r.sold) * Decimal("2.40")
    assert r.average_weight_kg == Decimal("2.40")
    assert r.cost_per_kg == (r.total_cost / total_kg).quantize(Decimal("0.01"))


def test_insights_only_claim_what_the_numbers_show(closed_batch):
    r = report_service.build(closed_batch)
    assert r.insights
    # Mortality on this fixture is 5.0%, which is inside the mark.
    assert any("Mortality" in note for note in r.insights)
    assert any("biggest cost" in note for note in r.insights)


def test_a_second_cycle_is_compared_with_the_first(closed_batch, farm, broiler):
    """"Cost per bird is down 8%" is only meaningful against a real previous cycle."""
    from datetime import date

    from apps.flocks.models import DailyLog

    later = Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Batch D",
        started_on=date.today() - timedelta(days=10),
        stocked=500,
        cost_per_bird=Decimal("600"),  # cheaper chicks, so cost per bird should fall
    )
    DailyLog.objects.create(
        batch=later,
        logged_on=later.started_on,
        feed_kg=Decimal("20"),
        deaths=1,
        feed_cost=Decimal("14400"),
    )
    Sale.objects.create(
        batch=later,
        sold_on=date.today(),
        kind=Sale.Kind.FULL,
        birds=499,
        average_weight_kg=Decimal("2.40"),
        revenue=Decimal("3832000"),
    )
    later.status = Batch.Status.CLOSED
    later.closed_on = date.today()
    later.save(update_fields=["status", "closed_on"])

    previous = report_service.build(closed_batch)
    report = report_service.build(later, previous=previous)

    assert any("Cost per bird is down" in note for note in report.insights)


def test_the_farm_listing_is_newest_first(closed_batch, farm):
    reports = report_service.for_farm(farm.id, period="all")
    assert reports
    assert reports == sorted(reports, key=lambda r: r.started_on, reverse=True)


def test_the_cost_insight_names_the_cost_that_actually_dominated(closed_batch):
    """
    An observation that contradicts the table beside it is worse than no
    observation. Whatever the largest line is, that is what gets named.
    """
    r = report_service.build(closed_batch)
    largest = max(r.costs, key=lambda c: c.amount)
    assert any(
        note.startswith(f"{largest.category} was your biggest cost") for note in r.insights
    )


def test_an_impossible_feed_conversion_is_flagged_not_celebrated(logged_batch):
    """
    A mistyped sale weight can produce a ratio under 1, which would read as an
    extraordinary result. It is a broken record, and the farmer should be told
    rather than congratulated.
    """
    from apps.insights.services import alerts as alert_service

    # A partial sale sets the flock's assumed weight. At 21 days these birds
    # weigh about 0.8kg, so 2.4kg is the kind of slip a farmer makes at dusk.
    Sale.objects.create(
        batch=logged_batch,
        sold_on=logged_batch.started_on + timedelta(days=20),
        kind=Sale.Kind.PARTIAL,
        birds=10,
        average_weight_kg=Decimal("2.40"),
        revenue=Decimal("76800"),
    )

    metrics = metrics_service.compute(logged_batch)
    assert metrics.feed_conversion is not None and metrics.feed_conversion < 1

    ids = {a.id for a in alert_service.for_batch(logged_batch)}
    assert "fcr-implausible" in ids
