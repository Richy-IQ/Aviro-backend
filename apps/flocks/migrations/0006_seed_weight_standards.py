"""
Target live weight by day, per bird type.

Points on a published growth curve rather than a formula: a layer pullet and a
broiler are not the same shape, and a figure that turns out to be wrong for
Nigerian conditions should be correctable without a code change.

The assertions below are the point of this file. A mistyped gram value would
otherwise tell a farmer their birds are behind when they are fine, or fine when
they are behind — and the second is the kind of mistake that is only discovered
at the point of sale.
"""

from itertools import pairwise

from django.db import migrations

# day: grams. Day 0 is the day-old chick.
STANDARDS = {
    "broiler": {0: 42, 7: 170, 14: 430, 21: 850, 28: 1400, 35: 2000, 42: 2600},
    "mixed": {0: 42, 7: 170, 14: 430, 21: 850, 28: 1400, 35: 2000, 42: 2600},
    "layer": {
        0: 38,
        7: 60,
        14: 110,
        28: 260,
        42: 420,
        70: 750,
        98: 1100,
        126: 1400,
        140: 1500,
    },
    "cockerel": {0: 40, 7: 90, 14: 180, 28: 450, 56: 900, 84: 1400, 112: 1800},
    "noiler": {0: 40, 7: 120, 14: 250, 28: 600, 56: 1200, 98: 1800},
}

# What the bird should weigh at the end of its cycle, as a sanity range. These
# are the figures a farmer sells on, so they are the ones worth guarding.
EXPECTED_FINAL_G = {
    "broiler": (2200, 3000),
    "mixed": (2200, 3000),
    "layer": (1300, 1700),
    "cockerel": (1500, 2200),
    "noiler": (1500, 2200),
}


def seed(apps, schema_editor):
    BirdType = apps.get_model("flocks", "BirdType")
    WeightStandard = apps.get_model("flocks", "WeightStandard")

    for code, points in STANDARDS.items():
        bird_type = BirdType.objects.filter(code=code).first()
        if bird_type is None:
            continue

        days = sorted(points)
        weights = [points[d] for d in days]

        # A growth curve that goes down is a typo, every time.
        assert all(b > a for a, b in pairwise(weights)), (
            f"{code}: weight must rise with every point, got {weights}"
        )

        low, high = EXPECTED_FINAL_G[code]
        assert low <= weights[-1] <= high, (
            f"{code}: final weight {weights[-1]}g is outside the expected {low}-{high}g"
        )

        # The curve has to cover the cycle the app tells the farmer to run.
        assert days[-1] >= bird_type.cycle_days - 1, (
            f"{code}: standards stop at day {days[-1]} but the cycle runs "
            f"{bird_type.cycle_days} days"
        )

        for day, grams in points.items():
            WeightStandard.objects.update_or_create(
                bird_type=bird_type, day=day, defaults={"grams": grams}
            )


def unseed(apps, schema_editor):
    apps.get_model("flocks", "WeightStandard").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("flocks", "0005_weighing")]
    operations = [migrations.RunPython(seed, unseed)]
