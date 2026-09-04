"""
Identity.

The account is a person, not a farm. A farmer owns one farm; a manager they
invite verifies their own number and joins that same farm through a Membership.
Modelling the account as the farm would leave invites nowhere to go.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, TimestampedModel

from .phone import to_e164


class UserManager(BaseUserManager):
    """Creates users from a phone number; passwords are optional by design."""

    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra):
        if not phone:
            raise ValueError("A phone number is required.")
        user = self.model(phone=to_e164(phone), **extra)
        # Farmers sign in with a one-time code, so most users never have a
        # usable password. Staff created below do.
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if not password:
            raise ValueError("Superusers must have a password.")
        return self.create_user(phone, password, **extra)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    """A person who uses Aviro."""

    phone = models.CharField(
        max_length=16,
        unique=True,
        help_text="E.164, e.g. +2348034129087.",
    )
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)

    # Asked on the screens where it changes an answer — feed prices and
    # benchmarks — rather than at sign-up.
    state = models.CharField(max_length=60, blank=True)
    lga = models.CharField(max_length=60, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.display_name or self.phone

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()

    def mark_phone_verified(self) -> None:
        self.phone_verified_at = timezone.now()
        self.save(update_fields=["phone_verified_at", "updated_at"])


class OtpCode(TimestampedModel):
    """
    A one-time code sent to a phone number.

    The code is hashed, never stored in the clear: anyone with read access to
    the database would otherwise be able to sign in as any farmer. Rows are kept
    after use so that repeated failures are visible.
    """

    LIFETIME = timedelta(minutes=10)
    MAX_ATTEMPTS = 5
    LENGTH = 6

    phone = models.CharField(max_length=16, db_index=True)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_otp_code"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["phone", "-created_at"])]

    def __str__(self) -> str:
        return f"OTP for {self.phone}"

    @classmethod
    def issue(cls, phone: str) -> tuple[OtpCode, str]:
        """
        Create a code for this number and return it with the plaintext.

        The plaintext is returned only so the delivery layer can send it; it is
        never persisted and never logged outside development.
        """
        code = f"{secrets.randbelow(10**cls.LENGTH):0{cls.LENGTH}d}"
        instance = cls.objects.create(
            phone=phone,
            code_hash=make_password(code),
            expires_at=timezone.now() + cls.LIFETIME,
        )
        return instance, code

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        return (
            not self.is_expired
            and self.consumed_at is None
            and self.attempts < self.MAX_ATTEMPTS
        )

    def verify(self, code: str) -> bool:
        """Check a submitted code, counting the attempt either way."""
        self.attempts += 1
        matched = check_password(code, self.code_hash)
        if matched:
            self.consumed_at = timezone.now()
        self.save(update_fields=["attempts", "consumed_at", "updated_at"])
        return matched
