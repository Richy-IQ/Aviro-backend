"""
Bring target weights down to what Nigerian farms actually achieve.

The figures seeded in 0006 were breed-standard: what a Cobb 500 reaches in a
climate-controlled house on a controlled ration. Smallholder flocks here run
below that — heat, open housing, and feed of varying quality all cost weight —
and a target nobody hits is worse than no target. A farmer whose birds are
doing fine would have been told every week that they were 20% behind, and would
have learned to ignore the app.

The old figures were also inconsistent with the feeding programme seeded in
0004. That programme feeds a broiler about 4kg to market; against the old 2.6kg
target it implied a feed conversion of 1.55, which is a breed-standard figure,
not one seen on a farm here. Against these it implies about 1.9, which is.

That relationship is now asserted rather than left to be noticed later: the two
seeded datasets describe the same bird, and if one is edited without the other
this migration fails.
"""

from itertools import pairwise

from django.db import migrations

# day: grams, revised for Nigerian smallholder conditions.
STANDARDS = {
    "broiler": {0: 42, 7: 150, 14: 360, 21: 700, 28: 1150, 35: 1650, 42: 2100},
    "mixed": {0: 42, 7: 150, 14: 360, 21: 700, 28: 1150, 35: 1650, 42: 2100},
    "layer": {
        0: 38,
        7: 55,
        14: 100,
        28: 240,
        42: 390,
        70: 700,
        98: 1030,
        126: 1300,
        140: 1400,
    },
    "cockerel": {0: 40, 7: 80, 14: 160, 28: 400, 56: 800, 84: 1200, 112: 1500},
    "noiler": {0: 40, 7: 110, 14: 220, 28: 520, 56: 1050, 98: 1600},
}

EXPECTED_FINAL_G = {
    "broiler": (1800, 2400),
    "mixed": (1800, 2400),
    "layer": (1250, 1550),
    "cockerel": (1300, 1800),
    "noiler": (1350, 1900),
}

# Feed against final weight, per bird. The bands differ by bird because the
# birds differ: a broiler is bred to convert feed, a cockerel is not and takes
# four months to get there. Judging a cockerel by a broiler's ratio is how you
# conclude something is broken when it is merely a cockerel.
#
# A layer's rearing feed is not a conversion figure at all — it buys a bird
# that then lays for a year — so layers are left out entirely.
#
# Each band is wide enough that ordinary revision passes and narrow enough that
# a decimal in the wrong place does not.
PLAUSIBLE_FCR = {
    "broiler": (1.4, 2.3),
    "mixed": (1.4, 2.3),
    "noiler": (2.2, 4.5),
    "cockerel": (3.5, 5.5),
}


def _feed_per_bird_kg(phases) -> float:
    """
    Total feed for one bird across the programme.

    Reimplements the interpolation from FeedPhase.grams_on, because a migration
    gets the historical model and none of its methods.
    """
    grams = 0.0
    for phase in phases:
        days = phase.day_to - phase.day_from + 1
        for day in range(phase.day_from, phase.day_to + 1):
            if days <= 1:
                grams += phase.grams_per_bird_start
                continue
            progress = (day - phase.day_from) / (days - 1)
            span = phase.grams_per_bird_end - phase.grams_per_bird_start
            grams += phase.grams_per_bird_start + span * progress
    return grams / 1000


def seed(apps, schema_editor):
    BirdType = apps.get_model("flocks", "BirdType")
    FeedPhase = apps.get_model("flocks", "FeedPhase")
    WeightStandard = apps.get_model("flocks", "WeightStandard")

    for code, points in STANDARDS.items():
        bird_type = BirdType.objects.filter(code=code).first()
        if bird_type is None:
            continue

        days = sorted(points)
        weights = [points[d] for d in days]

        assert all(b > a for a, b in pairwise(weights)), (
            f"{code}: weight must rise with every point, got {weights}"
        )

        low, high = EXPECTED_FINAL_G[code]
        assert low <= weights[-1] <= high, (
            f"{code}: final weight {weights[-1]}g is outside the expected {low}-{high}g"
        )

        assert days[-1] >= bird_type.cycle_days - 1, (
            f"{code}: standards stop at day {days[-1]} but the cycle runs "
            f"{bird_type.cycle_days} days"
        )

        # The feeding programme and the weight curve describe the same bird.
        if code in PLAUSIBLE_FCR:
            phases = list(FeedPhase.objects.filter(bird_type=bird_type).order_by("day_from"))
            if phases:
                feed_kg = _feed_per_bird_kg(phases)
                implied = feed_kg / (weights[-1] / 1000)
                lo, hi = PLAUSIBLE_FCR[code]
                assert lo <= implied <= hi, (
                    f"{code}: {feed_kg:.2f}kg of feed for a {weights[-1]}g bird implies a "
                    f"feed conversion of {implied:.2f}, outside {lo}-{hi}. The feeding "
                    f"programme and the weight standard disagree about this bird."
                )

        # Days that no longer appear in the curve must not survive as strays.
        WeightStandard.objects.filter(bird_type=bird_type).exclude(day__in=days).delete()
        for day, grams in points.items():
            WeightStandard.objects.update_or_create(
                bird_type=bird_type, day=day, defaults={"grams": grams}
            )


def unseed(apps, schema_editor):
    """Nothing to undo: 0006 rewrites these rows on its own way back."""


class Migration(migrations.Migration):
    dependencies = [("flocks", "0006_seed_weight_standards")]
    operations = [migrations.RunPython(seed, unseed)]
