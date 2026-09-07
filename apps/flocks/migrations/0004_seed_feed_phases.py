"""
Seed the feeding programme for each kind of bird.

Figures follow published breed-management guides — a broiler eats roughly 4kg
to reach market, a pullet roughly 8kg to reach point of lay. Actual intake
moves with temperature, feed quality and management, which is why the plan
built from these is presented as a guide to weigh against the birds rather
than a promise.

Cumulative totals are asserted below, so a mistyped figure fails the migration
rather than quietly telling a farmer to buy the wrong number of bags.
"""

from django.db import migrations

# bird_type_code: [(name, day_from, day_to, grams_start, grams_end, notes)]
FEED_PHASES = {
    "broiler": [
        (
            "Starter", 1, 14, 12, 55,
            "Crumbs. High protein, for frame and feather. Keep it in front of them all day.",
        ),
        (
            "Grower", 15, 28, 60, 120,
            "Change over three days by mixing into the old feed. A sudden switch costs a week of growth.",
        ),
        (
            "Finisher", 29, 42, 130, 200,
            "Most of your feed money is spent here. Observe any drug withdrawal period before selling.",
        ),
    ],
    "layer": [
        (
            "Chick mash", 1, 28, 10, 35,
            "Small particles. Brooding runs four weeks for layers, not two.",
        ),
        (
            "Grower mash", 29, 70, 38, 60,
            "Chase uniformity, not just average weight. Uneven pullets peak lower.",
        ),
        (
            "Developer", 71, 126, 62, 80,
            "Do not increase light hours yet. Early lay on an unready frame causes prolapse.",
        ),
        (
            "Layer mash", 127, 140, 85, 100,
            "Switch before the first egg, not after — she needs the calcium for shells.",
        ),
    ],
    "cockerel": [
        ("Chick mash", 1, 21, 10, 35, "Slower growing than broilers, so brooding runs three weeks."),
        ("Grower mash", 22, 84, 38, 85, "Cheaper feed suits them. Forage supplements it well."),
        ("Finisher", 85, 112, 88, 110, "Hold for festive demand if the price is close."),
    ],
    "noiler": [
        ("Chick mash", 1, 21, 10, 35, "Hardy, but they still need a warm, well-fed start."),
        (
            "Grower mash", 22, 70, 38, 80,
            "Ranging cuts this cost, but forage supplements feed — it does not replace it.",
        ),
        ("Finisher", 71, 98, 82, 105, "Males sell for meat; keep the females for eggs."),
    ],
    "mixed": [
        ("Starter", 1, 14, 12, 55, "Follow the programme for the birds the batch actually holds."),
        ("Grower", 15, 28, 60, 120, ""),
        ("Finisher", 29, 42, 130, 200, ""),
    ],
}

# Roughly what each bird should have eaten by the end of its cycle, in kg.
# A broiler at 4kg for a 2.5kg carcass is the familiar 1.6–1.7 conversion.
EXPECTED_TOTAL_KG = {
    "broiler": (3.8, 4.4),
    "layer": (7.0, 8.6),
    "cockerel": (5.5, 7.5),
    "noiler": (4.5, 6.5),
    "mixed": (3.8, 4.4),
}


def _cumulative_kg(phases) -> float:
    """Sum the interpolated daily intake across every phase, in kg per bird."""
    grams = 0.0
    for _, day_from, day_to, start, end, _ in phases:
        days = day_to - day_from + 1
        for offset in range(days):
            progress = offset / (days - 1) if days > 1 else 0
            grams += start + (end - start) * progress
    return grams / 1000


def seed(apps, schema_editor):
    BirdType = apps.get_model("flocks", "BirdType")
    FeedPhase = apps.get_model("flocks", "FeedPhase")

    for code, phases in FEED_PHASES.items():
        total = _cumulative_kg(phases)
        low, high = EXPECTED_TOTAL_KG[code]
        if not low <= total <= high:
            raise ValueError(
                f"{code}: feed programme totals {total:.2f}kg per bird, "
                f"outside the expected {low}–{high}kg. Check the figures."
            )

        bird_type = BirdType.objects.filter(code=code).first()
        if bird_type is None:
            continue

        for name, day_from, day_to, start, end, notes in phases:
            FeedPhase.objects.update_or_create(
                bird_type=bird_type,
                day_from=day_from,
                defaults={
                    "name": name,
                    "day_to": day_to,
                    "grams_per_bird_start": start,
                    "grams_per_bird_end": end,
                    "notes": notes,
                },
            )


def unseed(apps, schema_editor):
    apps.get_model("flocks", "FeedPhase").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("flocks", "0003_feedphase")]
    operations = [migrations.RunPython(seed, unseed)]
