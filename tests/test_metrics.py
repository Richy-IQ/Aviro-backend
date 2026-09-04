"""
The calculation engine.

These are the numbers a farmer decides when to sell on, so they get the most
scrutiny in the suite. A wrong figure here costs someone real money.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import DailyLog, Sale
from apps.flocks.services import metrics as metrics_service

pytestmark = pytest.mark.django_db


def test_an_unlogged_batch_still_reports_its_stock(batch):
    m = metrics_service.compute(batch)
    assert m.alive == 500
    assert m.deaths == 0
    assert m.mortality_pct == Decimal("0.0")
    # Cost of the chicks is known before any log exists.
    assert m.total_cost == Decimal("425000.00")


def test_deaths_reduce_the_living_count_and_raise_mortality(logged_batch):
    m = metrics_service.compute(logged_batch)
    assert m.deaths == 25
    assert m.alive == 475
    assert m.mortality_pct == Decimal("5.0")


def test_cost_per_bird_spreads_cost_over_survivors_not_over_stock(logged_batch):
    """
    A bird that died still ate. Dividing by survivors is what makes cost per
    bird comparable to the price a buyer offers.
    """
    m = metrics_service.compute(logged_batch)
    assert m.cost_per_bird == (m.total_cost / m.alive).quantize(Decimal("0.01"))
    assert m.cost_per_bird > m.total_cost / logged_batch.stocked


def test_feed_conversion_is_feed_over_live_mass(logged_batch):
    m = metrics_service.compute(logged_batch)
    live_mass = Decimal(m.alive) * m.average_weight_kg
    assert m.feed_conversion == (m.total_feed_kg / live_mass).quantize(Decimal("0.01"))


def test_a_recorded_sale_weight_beats_the_growth_curve(logged_batch):
    """A weighed bird is fact; the curve is an estimate. Fact wins."""
    before = metrics_service.compute(logged_batch).average_weight_kg

    Sale.objects.create(
        batch=logged_batch,
        sold_on=logged_batch.started_on + timedelta(days=20),
        kind=Sale.Kind.PARTIAL,
        birds=10,
        average_weight_kg=Decimal("2.50"),
        revenue=Decimal("80000"),
    )

    after = metrics_service.compute(logged_batch).average_weight_kg
    assert after == Decimal("2.50")
    assert after != before


def test_sold_birds_leave_the_living_count(logged_batch):
    Sale.objects.create(
        batch=logged_batch,
        sold_on=logged_batch.started_on + timedelta(days=20),
        kind=Sale.Kind.PARTIAL,
        birds=100,
        average_weight_kg=Decimal("2.00"),
        revenue=Decimal("640000"),
    )
    m = metrics_service.compute(logged_batch)
    assert m.alive == 500 - 25 - 100


def test_the_sell_window_peaks_and_the_optimal_day_is_that_peak(logged_batch):
    """
    The whole point of the curve: past some day, feed costs more than the
    weight it buys. If the peak were the last day, the advice would be
    meaningless.
    """
    m = metrics_service.compute(logged_batch)
    assert m.sell_window
    peak = max(m.sell_window, key=lambda p: p.projected_profit)
    assert m.optimal_sell_day == peak.day

    # The curve must actually turn over. If the best day were always the last
    # day in the window, the advice would reduce to "wait forever" and the
    # feature would be worse than useless.
    assert m.sell_window_peaks is True
    assert peak.day < m.sell_window[-1].day


def test_holding_birds_eventually_costs_more_than_it_earns(logged_batch):
    """
    Past the peak, each extra day must reduce projected profit. This is the
    single claim the sell-window feature makes to a farmer.
    """
    m = metrics_service.compute(logged_batch)
    after_peak = [p for p in m.sell_window if p.day > m.optimal_sell_day]
    assert after_peak, "the window should extend past the peak"

    profits = [p.projected_profit for p in after_peak]
    assert profits == sorted(profits, reverse=True), "profit should decline after the peak"


def test_the_growth_curve_plateaus(logged_batch):
    """A bird that never stops accelerating would never have a best day to sell."""
    m = metrics_service.compute(logged_batch)
    gains = [
        b.weight_kg - a.weight_kg
        for a, b in zip(m.sell_window, m.sell_window[1:], strict=False)
    ]
    assert gains[-1] < gains[0], "daily weight gain should slow as the bird matures"


def test_layers_get_no_invented_weight(db, farm, logged_batch):
    """
    Only the broiler growth curve is characterised. For other birds an
    estimate would be a guess dressed as data, so the API returns nothing.
    """
    from apps.flocks.models import Batch, BirdType

    layer_batch = Batch.objects.create(
        farm=farm,
        bird_type=BirdType.objects.get(code="layer"),
        name="Layer flock",
        started_on=logged_batch.started_on,
        stocked=200,
        cost_per_bird=Decimal("1200"),
    )
    m = metrics_service.compute(layer_batch)
    assert m.average_weight_kg is None
    assert m.feed_conversion is None
    assert m.sell_window == []
    # The layer's own cycle length, not the broiler's.
    assert m.cycle_days == 140


def test_streak_counts_consecutive_days_and_breaks_on_a_gap(logged_batch):
    assert metrics_service.compute(logged_batch).streak_days == 21

    DailyLog.objects.filter(
        batch=logged_batch, logged_on=logged_batch.started_on + timedelta(days=19)
    ).delete()

    # The gap is yesterday, so only today counts.
    assert metrics_service.compute(logged_batch).streak_days == 1


def test_feed_conversion_is_withheld_while_it_would_be_noise(db, farm, broiler):
    """
    A day-old chick weighs 45g. One bag of feed against that mass produces a
    ratio near 5 and a "behind" verdict on a flock doing nothing wrong, so the
    number is withheld until it means something.
    """
    from datetime import date
    from decimal import Decimal

    from apps.flocks.models import Batch, DailyLog

    fresh = Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Day one",
        started_on=date.today(),
        stocked=500,
        cost_per_bird=Decimal("850"),
    )
    DailyLog.objects.create(
        batch=fresh, logged_on=date.today(), feed_kg=Decimal("100"), deaths=3
    )

    assert metrics_service.compute(fresh).feed_conversion is None
