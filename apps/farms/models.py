"""
Farms and who may act on them.

Access is a three-way relationship — a person, a farm, and what they may do
there — because a farm has an owner, often a manager, and sometimes attendants
who are trusted with one pen and not the books.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Farm(BaseModel):
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=60, blank=True)
    lga = models.CharField(max_length=60, blank=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Membership",
        # Membership also points at User via invited_by, so the join has to be
        # named explicitly.
        through_fields=("farm", "user"),
        related_name="farms",
    )

    class Meta:
        db_table = "farms_farm"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def location(self) -> str:
        return ", ".join(part for part in (self.lga, self.state) if part)


class Pen(BaseModel):
    """A physical house or pen. Optional — many farms run a single space."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="pens")
    name = models.CharField(max_length=60)

    class Meta:
        db_table = "farms_pen"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["farm", "name"], name="unique_pen_name_per_farm"),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.farm.name}"


class Membership(BaseModel):
    """
    One person's access to one farm.

    An invited manager verifies their own phone number and joins here, which is
    why the account is a person rather than a farm.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Farm manager"
        ATTENDANT = "attendant", "Pen attendant"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)

    # Empty means the whole farm. Attendants are usually scoped to their pens.
    pens = models.ManyToManyField(Pen, blank=True, related_name="attendants")

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "farms_membership"
        ordering = ["role", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "farm"], name="unique_membership_per_farm"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()} at {self.farm}"

    @property
    def can_write(self) -> bool:
        """Viewers read the numbers; everyone else may record against them."""
        return self.role != self.Role.VIEWER

    @property
    def can_manage_team(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.MANAGER}

    @property
    def sees_money(self) -> bool:
        """Attendants log birds; they are not shown what the farm earns."""
        return self.role in {self.Role.OWNER, self.Role.MANAGER, self.Role.VIEWER}
