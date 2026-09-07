"""
The weekly and monthly farm report.

A farmer reads this to decide whether the week went well. The comparison with
the window before is the whole point — fourteen deaths means nothing until you
know last week was three.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import DailyLog
from apps.insights.services import period as period_service

pytestmark = pytest.mark.django_db


def log(batch, days_ago: int, *, feed="10", deaths=0, feed_cost="0", other="0"):
    return DailyLog.objects.create(
        batch=batch,
        logged_on=date.today() - timedelta(days=days_ago),
        feed_kg=Decimal(feed),
        deaths=deaths,
        feed_cost=Decimal(feed_cost),
        other_cost=Decimal(other),
    )


def test_a_quiet_week_reads_as_a_quiet_week(batch, farm):
    for d in range(7):
        log(batch, d, deaths=0)

    r = period_service.build(farm.id, period="week")
    assert r.deaths == 0
    assert "lost no birds" in r.headline


def test_deaths_are_compared_with_the_week_before(batch, farm):
    for d in range(7):
        log(batch, d, deaths=1)
    for d in range(7, 14):
        log(batch, d, deaths=5)

    r = period_service.build(farm.id, period="week")
    assert r.deaths == 7
    assert r.deaths_before == 35
    assert "better than 35" in r.headline


def test_a_worse_week_says_so(batch, farm):
    for d in range(7):
        log(batch, d, deaths=4)
    for d in range(7, 14):
        log(batch, d, deaths=1)

    r = period_service.build(farm.id, period="week")
    assert "up from 7" in r.headline


def test_missed_days_are_named_rather_than_counted_as_good(batch, farm):
    """A day with no entry is not a day with no deaths, and the report must say so."""
    log(batch, 0)
    log(batch, 1)

    r = period_service.build(farm.id, period="week")
    assert r.days_logged == 2
    assert any("were not logged" in n for n in r.notes)
    assert any("look better than the farm really did" in n for n in r.notes)


def test_logging_twice_in_a_day_is_still_one_day(batch, farm, broiler):
    """days_logged is the habit, not the row count."""
    from apps.flocks.models import Batch

    other = Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Second pen",
        started_on=date.today() - timedelta(days=20),
        stocked=100,
        cost_per_bird=Decimal("850.00"),
    )
    log(batch, 0)
    log(other, 0)

    assert period_service.build(farm.id, period="week").days_logged == 1


def test_unrecorded_feed_cost_is_declared_not_reported_as_zero(batch, farm):
    log(batch, 0, feed="25", other="500")

    r = period_service.build(farm.id, period="week")
    assert r.feed_cost_recorded is False
    assert any("No feed cost was recorded" in n for n in r.notes)
    # The spending that was recorded is still counted.
    assert r.recorded_spend == Decimal("500.00")


def test_a_farm_with_no_logs_is_told_plainly(batch, farm):
    r = period_service.build(farm.id, period="week")
    assert r.days_logged == 0
    assert "did not log any" in r.headline


def test_what_is_coming_is_listed_before_it_arrives(batch, farm, broiler):
    """A broiler at day 25 changes to Finisher on day 29, four days out."""
    from apps.flocks.models import Batch

    Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Nearly finishing",
        started_on=date.today() - timedelta(days=24),
        stocked=200,
        cost_per_bird=Decimal("850.00"),
    )

    r = period_service.build(farm.id, period="week")
    assert any("Change to Finisher" in u.what for u in r.upcoming)
    # Only what is ahead, and only inside the window being reported on.
    assert all(date.today() < u.due_on <= date.today() + timedelta(days=7) for u in r.upcoming)
    assert r.upcoming == sorted(r.upcoming, key=lambda u: u.due_on)


def test_the_month_is_a_wider_window_than_the_week(batch, farm):
    for d in range(20):
        log(batch, d, deaths=1)

    week = period_service.build(farm.id, period="week")
    month = period_service.build(farm.id, period="month")
    assert week.days == 7
    assert month.days == 30
    assert month.deaths > week.deaths


def test_feed_is_stated_in_bags_once_there_is_a_bag_of_it(batch, farm):
    log(batch, 0, feed="50")
    r = period_service.build(farm.id, period="week")
    assert r.feed_bags == Decimal("2.0")
    assert "2.0 bags" in r.headline
