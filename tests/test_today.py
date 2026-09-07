"""
Today's guidance.

This is the number a farmer weighs their scoop against, so it has to agree
with the plan they bought feed on. Where the two disagree the app has lied to
someone twice.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import Batch, VaccinationSchedule
from apps.flocks.services import plan as plan_service
from apps.flocks.services import today as today_service

pytestmark = pytest.mark.django_db


def guidance(batch, alive, on=None):
    return today_service.build(batch, alive=alive, on=on or date.today())


def test_the_daily_target_agrees_with_the_plan(batch, broiler):
    """
    Summing the daily targets across a phase must land on the phase total the
    plan quoted. Two sources for one number is how a farmer ends up short.
    """
    cycle = plan_service.build(broiler, stocked=500, started_on=batch.started_on)
    starter = next(p for p in cycle.phases if p.name == "Starter")

    total = Decimal("0")
    for day in range(starter.day_from, starter.day_to + 1):
        on = batch.started_on + timedelta(days=day - 1)
        total += guidance(batch, 500, on).expected_kg

    assert abs(total - starter.total_kg) <= Decimal("0.5")


def test_feed_is_quoted_for_the_birds_still_alive(batch):
    """A flock that lost a hundred birds must not be fed for a hundred birds."""
    full = guidance(batch, 500).expected_kg
    reduced = guidance(batch, 400).expected_kg
    assert reduced < full
    assert abs(reduced / full - Decimal("0.8")) < Decimal("0.01")


def test_the_band_brackets_the_target(batch):
    g = guidance(batch, 500)
    assert g.low_kg < g.expected_kg < g.high_kg


def test_a_day_names_the_phase_the_birds_are_in(batch):
    """Day 21 of a broiler is Grower, not Starter."""
    assert guidance(batch, 500).day == 21
    assert guidance(batch, 500).phase_name == "Grower"


def test_the_next_feed_change_is_announced_before_it_happens(batch):
    g = guidance(batch, 500)
    assert g.next_phase_name == "Finisher"
    assert g.days_until_change == 8
    assert g.next_phase_starts_on == batch.started_on + timedelta(days=28)


def test_a_dose_due_today_is_separated_from_one_due_soon(batch, broiler):
    """The farmer is standing in the pen: today is an instruction, soon is a heads-up."""
    VaccinationSchedule.objects.create(bird_type=broiler, day=21, name="Test dose", route="Water")
    VaccinationSchedule.objects.create(bird_type=broiler, day=23, name="Later dose", route="Water")
    VaccinationSchedule.objects.create(bird_type=broiler, day=40, name="Far dose", route="Water")

    g = guidance(batch, 500)
    today_names = {d.name for d in g.due_today}
    soon_names = {d.name for d in g.due_soon}

    assert "Test dose" in today_names
    assert "Later dose" in soon_names
    # A dose nineteen days out is noise while someone is logging today.
    assert "Far dose" not in today_names | soon_names
    assert not today_names & soon_names


def test_small_flocks_are_not_nagged_about_a_single_death(batch):
    """Half a percent of 100 birds is not a reason to raise a question."""
    assert guidance(batch, 100).deaths_watch_from == today_service.DEATHS_WATCH_FLOOR
    assert guidance(batch, 2000).deaths_watch_from == 10


def test_birds_past_the_programme_still_get_a_log_screen(farm, broiler):
    """A broiler held back for a buyer has no phase left, and that is not an error."""
    old = Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Held back",
        started_on=date.today() - timedelta(days=60),
        stocked=100,
        cost_per_bird=Decimal("850.00"),
    )
    g = guidance(old, 90)
    assert g.phase_name is None
    assert g.expected_kg is None
    assert g.deaths_watch_from >= today_service.DEATHS_WATCH_FLOOR


def test_a_layer_is_not_given_a_broilers_target(farm):
    """The whole point of keying this to bird type."""
    from apps.flocks.models import BirdType

    layer_type = BirdType.objects.get(code="layer")
    layer_batch = Batch.objects.create(
        farm=farm,
        bird_type=layer_type,
        name="Layers",
        started_on=date.today() - timedelta(days=20),
        stocked=500,
        cost_per_bird=Decimal("1200.00"),
    )
    assert guidance(layer_batch, 500).phase_name != guidance_broiler_phase(farm)


def guidance_broiler_phase(farm):
    from apps.flocks.models import BirdType

    broiler = BirdType.objects.get(code="broiler")
    b = Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Broilers for comparison",
        started_on=date.today() - timedelta(days=20),
        stocked=500,
        cost_per_bird=Decimal("850.00"),
    )
    return today_service.build(b, alive=500, on=date.today()).phase_name
