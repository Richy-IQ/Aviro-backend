"""
Birds, and what happens to them day by day.

The daily log is the record everything else is derived from. Feed conversion,
mortality, cost per bird and the best day to sell are all computed from these
rows rather than stored, so a corrected entry corrects every number that
depends on it.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BaseModel
from apps.farms.models import Farm, Pen


class BirdType(BaseModel):
    """
    A kind of bird, with the cycle it implies.

    Cycle length belongs here rather than on the batch: a broiler is finished
    in six weeks and a layer rears for twenty before laying, and treating them
    alike is wrong for both.
    """

    class Code(models.TextChoices):
        BROILER = "broiler", "Broilers"
        LAYER = "layer", "Layers"
        COCKEREL = "cockerel", "Cockerels"
        NOILER = "noiler", "Noilers"
        MIXED = "mixed", "Mixed"

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    label = models.CharField(max_length=60)
    description = models.CharField(max_length=200, blank=True)

    cycle_days = models.PositiveSmallIntegerField(
        help_text="Days to the milestone the farmer is working towards."
    )
    cycle_goal = models.CharField(
        max_length=60, help_text="What that milestone is, e.g. 'to market', 'to first egg'."
    )

    class Meta:
        db_table = "flocks_bird_type"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.label


class Breed(BaseModel):
    name = models.CharField(max_length=60, unique=True)
    bird_type = models.ForeignKey(BirdType, on_delete=models.PROTECT, related_name="breeds")

    class Meta:
        db_table = "flocks_breed"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VaccinationSchedule(BaseModel):
    """
    A dose due on a given day of the cycle, for one kind of bird.

    Scoped to bird type on purpose: showing a layer keeper the broiler schedule
    would give them the wrong dates for a bird that lives fifteen times longer.
    """

    bird_type = models.ForeignKey(
        BirdType, on_delete=models.CASCADE, related_name="vaccination_schedule"
    )
    day = models.PositiveSmallIntegerField(help_text="Day of the cycle the dose is due.")
    name = models.CharField(max_length=120)
    route = models.CharField(max_length=60, help_text="How it is given, e.g. 'Drinking water'.")
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "flocks_vaccination_schedule"
        ordering = ["bird_type", "day"]
        constraints = [
            models.UniqueConstraint(
                fields=["bird_type", "day", "name"], name="unique_dose_per_type_and_day"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} — day {self.day}"


class Batch(BaseModel):
    """One set of birds raised together."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="batches")
    pen = models.ForeignKey(
        Pen, on_delete=models.SET_NULL, null=True, blank=True, related_name="batches"
    )
    bird_type = models.ForeignKey(BirdType, on_delete=models.PROTECT, related_name="batches")
    breed = models.ForeignKey(
        Breed, on_delete=models.PROTECT, null=True, blank=True, related_name="batches"
    )

    name = models.CharField(max_length=60)
    started_on = models.DateField(help_text="The day the birds were stocked.")

    stocked = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    cost_per_bird = models.DecimalField(max_digits=10, decimal_places=2)
    transport_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    supplier = models.CharField(max_length=120, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    closed_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "flocks_batch"
        ordering = ["-started_on", "name"]
        indexes = [models.Index(fields=["farm", "status"])]

    def __str__(self) -> str:
        return f"{self.name} · {self.farm.name}"

    @property
    def chick_cost(self) -> Decimal:
        return self.cost_per_bird * self.stocked + self.transport_cost


class DailyLog(BaseModel):
    """
    One evening's record for one batch.

    Unique per batch and date, so logging twice corrects rather than duplicates
    — a farmer who is unsure whether they already logged should be able to just
    log again.
    """

    class DeathCause(models.TextChoices):
        SUDDEN = "sudden", "Sudden death"
        DISEASE = "disease", "Disease symptoms"
        PREDATOR = "predator", "Predator"
        OTHER = "other", "Other"

    class HealthActivity(models.TextChoices):
        NONE = "none", "Nothing today"
        VACCINE = "vaccine", "Gave a vaccine"
        MEDICINE = "medicine", "Gave medicine"
        VET = "vet", "Vet visited"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="logs")
    logged_on = models.DateField()

    feed_kg = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(0)]
    )
    deaths = models.PositiveIntegerField(default=0)
    death_cause = models.CharField(max_length=20, choices=DeathCause.choices, blank=True)

    health_activity = models.CharField(
        max_length=20,
        choices=HealthActivity.choices,
        default=HealthActivity.NONE,
    )

    feed_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    meds_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    other_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "flocks_daily_log"
        ordering = ["-logged_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "logged_on"], name="one_log_per_batch_per_day"
            ),
        ]
        indexes = [models.Index(fields=["batch", "-logged_on"])]

    def __str__(self) -> str:
        return f"{self.batch.name} — {self.logged_on}"

    @property
    def day_in_cycle(self) -> int:
        """Day 1 is the day the birds were stocked."""
        return (self.logged_on - self.batch.started_on).days + 1

    @property
    def total_cost(self) -> Decimal:
        return self.feed_cost + self.meds_cost + self.other_cost


class Sale(BaseModel):
    """Birds leaving the farm. A full sale closes the batch."""

    class Kind(models.TextChoices):
        PARTIAL = "partial", "Partial sale"
        FULL = "full", "Full sale"

    class BuyerType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        RESTAURANT = "restaurant", "Restaurant"
        SUPERMARKET = "supermarket", "Supermarket"
        WHOLESALER = "wholesaler", "Wholesaler"
        OTHER = "other", "Other"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="sales")
    sold_on = models.DateField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PARTIAL)

    birds = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    average_weight_kg = models.DecimalField(max_digits=6, decimal_places=2)
    revenue = models.DecimalField(max_digits=14, decimal_places=2)

    buyer_type = models.CharField(max_length=20, choices=BuyerType.choices, blank=True)
    buyer_name = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "flocks_sale"
        ordering = ["-sold_on"]

    def __str__(self) -> str:
        return f"{self.birds} birds from {self.batch.name}"

    @property
    def price_per_kg(self) -> Decimal | None:
        weight = self.birds * self.average_weight_kg
        return self.revenue / weight if weight else None
