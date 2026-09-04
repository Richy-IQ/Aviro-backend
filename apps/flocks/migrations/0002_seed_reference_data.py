"""
Seed the reference data the app cannot function without.

Bird types, their cycle lengths and their vaccination schedules are not user
content — they are the domain. Shipping them as a migration means every
environment agrees, and a fresh database is immediately usable.
"""

from django.db import migrations

BIRD_TYPES = [
    {
        "code": "broiler",
        "label": "Broilers",
        "cycle_days": 42,
        "cycle_goal": "to market",
        "description": "Six weeks from chick to sale. Fast, feed-hungry and unforgiving.",
        "breeds": ["Cobb 500", "Ross 308", "Arbor Acres"],
        "vaccinations": [
            (1, "Marek + ND (HB1)", "Spray", ""),
            (7, "Newcastle + IB", "Eye drop", ""),
            (10, "Gumboro (IBD)", "Drinking water", "Use cool, unchlorinated water."),
            (14, "Gumboro booster", "Drinking water", ""),
            (21, "Newcastle (LaSota)", "Drinking water", "Withhold water 30 minutes before."),
            (28, "Fowl pox", "Wing-stab", ""),
        ],
    },
    {
        "code": "layer",
        "label": "Layers",
        "cycle_days": 140,
        "cycle_goal": "to first egg",
        "description": "Five months of rearing before a single egg, then over a year in lay.",
        "breeds": ["ISA Brown", "Lohmann Brown", "Nera Black"],
        "vaccinations": [
            (1, "Marek", "Subcutaneous", "Usually given at the hatchery."),
            (7, "Newcastle + IB", "Eye drop", ""),
            (14, "Gumboro (IBD)", "Drinking water", ""),
            (21, "Gumboro booster", "Drinking water", ""),
            (28, "Newcastle (LaSota)", "Drinking water", ""),
            (42, "Fowl pox", "Wing-stab", ""),
            (56, "Newcastle booster", "Drinking water", ""),
            (84, "Fowl typhoid", "Injection", ""),
            (112, "Newcastle before lay", "Injection", "Protects her through the laying period."),
        ],
    },
    {
        "code": "cockerel",
        "label": "Cockerels",
        "cycle_days": 112,
        "cycle_goal": "to market",
        "description": "Slow-growing and hardy, sold into local and festive demand.",
        "breeds": ["FUNAAB Alpha"],
        "vaccinations": [
            (1, "Marek + ND (HB1)", "Spray", ""),
            (10, "Gumboro (IBD)", "Drinking water", ""),
            (21, "Newcastle (LaSota)", "Drinking water", ""),
            (42, "Fowl pox", "Wing-stab", ""),
        ],
    },
    {
        "code": "noiler",
        "label": "Noilers",
        "cycle_days": 98,
        "cycle_goal": "to market weight",
        "description": "Dual purpose and hardy. Males for meat, females kept for eggs.",
        "breeds": ["Noiler"],
        "vaccinations": [
            (1, "Marek + ND (HB1)", "Spray", ""),
            (10, "Gumboro (IBD)", "Drinking water", ""),
            (21, "Newcastle (LaSota)", "Drinking water", ""),
            (42, "Fowl pox", "Wing-stab", ""),
        ],
    },
    {
        "code": "mixed",
        "label": "Mixed",
        "cycle_days": 42,
        "cycle_goal": "to market",
        "description": "More than one kind of bird in the same batch.",
        "breeds": [],
        "vaccinations": [],
    },
]


def seed(apps, schema_editor):
    BirdType = apps.get_model("flocks", "BirdType")
    Breed = apps.get_model("flocks", "Breed")
    VaccinationSchedule = apps.get_model("flocks", "VaccinationSchedule")

    for spec in BIRD_TYPES:
        bird_type, _ = BirdType.objects.update_or_create(
            code=spec["code"],
            defaults={
                "label": spec["label"],
                "cycle_days": spec["cycle_days"],
                "cycle_goal": spec["cycle_goal"],
                "description": spec["description"],
            },
        )
        for name in spec["breeds"]:
            Breed.objects.get_or_create(name=name, defaults={"bird_type": bird_type})
        for day, name, route, notes in spec["vaccinations"]:
            VaccinationSchedule.objects.get_or_create(
                bird_type=bird_type,
                day=day,
                name=name,
                defaults={"route": route, "notes": notes},
            )


def unseed(apps, schema_editor):
    apps.get_model("flocks", "BirdType").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("flocks", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
