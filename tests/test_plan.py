"""
The cycle plan.

A farmer buys feed against these numbers. Being wrong here means they run
short in week six, or tie up money they did not need to spend.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import BirdType
from apps.flocks.services import plan as plan_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def broiler_plan(broiler):
    return plan_service.build(broiler, stocked=500, started_on=date(2026, 9, 6))


def test_a_broiler_eats_about_four_kilograms_to_market(broiler_plan):
    """The familiar figure: ~4kg of feed for a ~2.5kg bird, a conversion near 1.6."""
    assert Decimal("3.8") <= broiler_plan.feed_per_bird_kg <= Decimal("4.4")


def test_the_phases_account_for_every_kilogram(broiler_plan):
    """If the phases do not sum to the total, one of the two is lying."""
    from_phases = sum(p.total_kg for p in broiler_plan.phases)
    assert abs(from_phases - broiler_plan.total_feed_kg) <= Decimal("0.5")


def test_the_weeks_account_for_every_kilogram_too(broiler_plan):
    from_weeks = sum(w.total_kg for w in broiler_plan.weeks)
    assert abs(from_weeks - broiler_plan.total_feed_kg) <= Decimal("0.5")


def test_phases_run_back_to_back_with_no_gap(broiler_plan):
    """A day that belongs to no phase is a day with no feeding instruction."""
    for earlier, later in zip(broiler_plan.phases, broiler_plan.phases[1:], strict=False):
        assert later.day_from == earlier.day_to + 1
        assert later.starts_on == earlier.ends_on + timedelta(days=1)


def test_feed_rises_across_the_cycle(broiler_plan):
    """Birds eat more every week. A plan that says otherwise is wrong."""
    weekly = [w.total_kg for w in broiler_plan.weeks]
    assert weekly == sorted(weekly), "weekly feed should never fall"
    assert weekly[-1] > weekly[0] * 3, "a finishing bird eats far more than a chick"


def test_doubling_the_birds_doubles_the_feed(broiler):
    small = plan_service.build(broiler, stocked=250, started_on=date(2026, 9, 6))
    large = plan_service.build(broiler, stocked=500, started_on=date(2026, 9, 6))
    assert large.total_feed_kg == pytest.approx(small.total_feed_kg * 2, abs=Decimal("0.5"))
    # Per bird is the same either way, which is what makes it comparable.
    assert small.feed_per_bird_kg == large.feed_per_bird_kg


def test_dates_follow_the_day_the_birds_were_stocked(broiler):
    start = date(2026, 11, 20)
    p = plan_service.build(broiler, stocked=100, started_on=start)

    assert p.phases[0].starts_on == start, "day 1 is the day they arrive"
    assert p.ends_on == start + timedelta(days=p.cycle_days - 1)
    first_dose = min(p.vaccinations, key=lambda v: v.day)
    assert first_dose.due_on == start + timedelta(days=first_dose.day - 1)


def test_vaccination_dates_are_real_dates_not_day_numbers(broiler_plan):
    """A farmer works from a calendar, not from "day 21"."""
    assert broiler_plan.vaccinations
    for dose in broiler_plan.vaccinations:
        assert dose.due_on == broiler_plan.started_on + timedelta(days=dose.day - 1)


def test_a_layer_gets_its_own_programme_not_a_broilers(db):
    """
    The whole point of keying this to bird type. A layer rears for months and
    eats roughly twice what a broiler does before it earns anything.
    """
    layer = BirdType.objects.get(code="layer")
    broiler = BirdType.objects.get(code="broiler")

    layer_plan = plan_service.build(layer, stocked=500, started_on=date(2026, 9, 6))
    broiler_plan = plan_service.build(broiler, stocked=500, started_on=date(2026, 9, 6))

    assert layer_plan.cycle_days == 140
    assert layer_plan.cycle_goal == "to first egg"
    assert layer_plan.feed_per_bird_kg > broiler_plan.feed_per_bird_kg * Decimal("1.5")
    assert {p.name for p in layer_plan.phases} != {p.name for p in broiler_plan.phases}


def test_bags_are_stated_because_that_is_how_feed_is_bought(broiler_plan):
    """25kg bags — a farmer buys bags, not kilograms."""
    assert broiler_plan.total_bags == pytest.approx(
        broiler_plan.total_feed_kg / 25, abs=Decimal("0.2")
    )
    for week in broiler_plan.weeks:
        assert week.bags == pytest.approx(week.total_kg / 25, abs=Decimal("0.2"))


def test_the_plan_says_it_is_an_estimate(broiler_plan):
    """A projection presented as fact is how someone ends up short of feed."""
    assert "guide" in broiler_plan.caveat.lower()
    assert "not a promise" in broiler_plan.caveat.lower()


def test_chick_cost_is_included_when_known(broiler):
    p = plan_service.build(
        broiler, stocked=500, started_on=date(2026, 9, 6), cost_per_bird=Decimal("850")
    )
    assert p.estimated_chick_cost == Decimal("425000.00")
    assert p.estimated_total_cost == p.estimated_feed_cost + p.estimated_chick_cost
    assert p.estimated_cost_per_bird == pytest.approx(
        p.estimated_total_cost / 500, abs=Decimal("0.01")
    )
