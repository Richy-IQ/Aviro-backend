"""
Birds on a scale.

Weight is the input that turns feed conversion from a model into a measurement.
Getting it wrong in either direction is expensive: a farmer told their birds are
behind will overfeed, and one told they are fine will sell light.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.flocks.models import Sale, Weighing
from apps.flocks.serializers import WeighingSerializer
from apps.flocks.services import metrics as metrics_service

pytestmark = pytest.mark.django_db


def weigh(batch, *, days_ago=0, birds=10, total="8.50"):
    return Weighing.objects.create(
        batch=batch,
        weighed_on=date.today() - timedelta(days=days_ago),
        birds_weighed=birds,
        total_weight_kg=Decimal(total),
    )


def test_the_average_is_derived_not_typed(batch):
    """A farmer holding ten birds and a scale should not also be doing division."""
    w = weigh(batch, birds=10, total="8.50")
    assert w.average_weight_kg == Decimal("0.85")


def test_a_weighing_beats_the_growth_curve(batch):
    """The whole point: measured weight replaces the model."""
    modelled = metrics_service.compute(batch)
    assert modelled.weight_source == "estimated"

    weigh(batch, birds=10, total="6.00")
    measured = metrics_service.compute(batch)

    assert measured.weight_source == "weighed"
    assert measured.average_weight_kg == Decimal("0.60")
    assert measured.average_weight_kg != modelled.average_weight_kg


def test_the_more_recent_measurement_wins(batch):
    Sale.objects.create(
        batch=batch,
        sold_on=date.today() - timedelta(days=5),
        birds=50,
        average_weight_kg=Decimal("1.90"),
        revenue=Decimal("200000"),
    )
    weigh(batch, days_ago=1, birds=10, total="21.00")

    m = metrics_service.compute(batch)
    assert m.weight_source == "weighed"
    assert m.average_weight_kg == Decimal("2.10")


def test_an_older_weighing_loses_to_a_newer_sale(batch):
    weigh(batch, days_ago=10, birds=10, total="10.00")
    Sale.objects.create(
        batch=batch,
        sold_on=date.today(),
        birds=50,
        average_weight_kg=Decimal("2.40"),
        revenue=Decimal("300000"),
    )
    m = metrics_service.compute(batch)
    assert m.weight_source == "sold"
    assert m.average_weight_kg == Decimal("2.40")


def test_feed_conversion_is_computed_from_the_scale_once_there_is_one(logged_batch):
    before = metrics_service.compute(logged_batch)
    weigh(logged_batch, birds=10, total="12.00")
    after = metrics_service.compute(logged_batch)

    assert before.weight_source == "estimated"
    assert after.weight_source == "weighed"
    assert after.feed_conversion != before.feed_conversion


def test_the_target_is_interpolated_between_published_points(batch, broiler):
    """Day 21 is a seeded point at 850g; day 24 must fall between 21 and 28."""
    day21 = metrics_service.target_weight_kg(batch, 21)
    day24 = metrics_service.target_weight_kg(batch, 24)
    day28 = metrics_service.target_weight_kg(batch, 28)

    assert day21 == Decimal("0.85")
    assert day28 == Decimal("1.40")
    assert day21 < day24 < day28


def test_the_comparison_is_only_made_against_a_real_measurement(batch):
    """Comparing a modelled weight with a published curve compares two models."""
    assert metrics_service.compute(batch).weight_vs_target_pct is None

    weigh(batch, birds=10, total="8.50")  # 0.85kg on day 21, exactly on target
    m = metrics_service.compute(batch)
    assert m.weight_vs_target_pct == Decimal("100.0")


def test_birds_behind_the_standard_show_it(batch):
    weigh(batch, birds=10, total="6.00")  # 0.60kg against a 0.85kg target
    m = metrics_service.compute(batch)
    assert m.weight_vs_target_pct is not None
    assert m.weight_vs_target_pct < Decimal("75")


def test_a_weight_that_cannot_be_a_bird_is_refused(batch):
    """Almost always the count and the total entered the wrong way round."""
    s = WeighingSerializer(
        data={"weighed_on": date.today(), "birds_weighed": 2, "total_weight_kg": "40.00"},
        context={"batch": batch},
    )
    assert not s.is_valid()
    assert "12kg" in str(s.errors)


def test_grams_mistaken_for_kilograms_is_refused(batch):
    s = WeighingSerializer(
        data={"weighed_on": date.today(), "birds_weighed": 10, "total_weight_kg": "0.05"},
        context={"batch": batch},
    )
    assert not s.is_valid()
    assert "grams" in str(s.errors)


def test_a_weighing_before_the_birds_arrived_is_refused(batch):
    s = WeighingSerializer(
        data={
            "weighed_on": batch.started_on - timedelta(days=1),
            "birds_weighed": 10,
            "total_weight_kg": "8.50",
        },
        context={"batch": batch},
    )
    assert not s.is_valid()
