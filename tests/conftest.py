from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.farms.models import Farm, Membership
from apps.flocks.models import Batch, BirdType, DailyLog


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(phone="08034129087")


@pytest.fixture
def farm(db, user) -> Farm:
    farm = Farm.objects.create(name="Adamu's Poultry", state="Oyo", lga="Ibadan North")
    Membership.objects.create(user=user, farm=farm, role=Membership.Role.OWNER)
    return farm


@pytest.fixture
def broiler(db) -> BirdType:
    return BirdType.objects.get(code="broiler")


@pytest.fixture
def batch(db, farm, broiler) -> Batch:
    """A batch stocked 20 days ago, so day_in_cycle is 21."""
    return Batch.objects.create(
        farm=farm,
        bird_type=broiler,
        name="Batch B",
        started_on=date.today() - timedelta(days=20),
        stocked=500,
        cost_per_bird=Decimal("850.00"),
    )


@pytest.fixture
def logged_batch(batch) -> Batch:
    """The same batch with 21 days of plausible logs behind it."""
    alive = batch.stocked
    for offset in range(21):
        died = 2 if offset < 4 else 1
        alive -= died
        DailyLog.objects.create(
            batch=batch,
            logged_on=batch.started_on + timedelta(days=offset),
            feed_kg=Decimal(str(round(alive * (18 + offset * 3.5) / 1000, 2))),
            deaths=died,
            feed_cost=Decimal("10000.00"),
            meds_cost=Decimal("0"),
            other_cost=Decimal("400.00"),
        )
    return batch


@pytest.fixture
def auth_client(db, user):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client
