"""
The cooperative view.

Two things have to hold. An officer must see which member is in trouble without
having to read fifty screens, and an officer must never be able to write in a
member's book. The second is the promise that makes a farmer willing to join.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.farms.models import Farm, Membership, Organisation, OrganisationMembership
from apps.flocks.models import Batch, DailyLog
from apps.insights.services import network as network_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def coop(db):
    return Organisation.objects.create(name="Ibadan Poultry Cooperative", state="Oyo")


@pytest.fixture
def officer(db, django_user_model):
    return django_user_model.objects.create_user(phone="08099887766")


@pytest.fixture
def member_farms(db, coop, broiler):
    farms = []
    for i in range(3):
        farm = Farm.objects.create(name=f"Member Farm {i + 1}", state="Oyo", organisation=coop)
        Batch.objects.create(
            farm=farm,
            bird_type=broiler,
            name="Batch 1",
            started_on=date.today() - timedelta(days=20),
            stocked=500,
            cost_per_bird=Decimal("850.00"),
        )
        farms.append(farm)
    return farms


def log(farm, days_ago, *, deaths=0, feed="20"):
    return DailyLog.objects.create(
        batch=farm.batches.first(),
        logged_on=date.today() - timedelta(days=days_ago),
        feed_kg=Decimal(feed),
        deaths=deaths,
    )


def test_a_farm_that_stopped_logging_is_surfaced(coop, member_farms):
    """A farm that goes quiet is usually a farm where something went wrong."""
    for f in member_farms:
        log(f, 0)
    # One of them last reported a week ago.
    DailyLog.objects.filter(batch__farm=member_farms[2]).delete()
    log(member_farms[2], 8)

    o = network_service.build(coop, period="week")
    silent = [r for r in o.rows if r.status == "silent"]

    assert [r.name for r in silent] == ["Member Farm 3"]
    assert "has not logged for 8 days" in silent[0].attention[0].lower()


def test_heavy_losses_outrank_a_quiet_farm(coop, member_farms):
    """An officer with ten minutes should spend them on the farm losing birds."""
    for f in member_farms:
        log(f, 0)
    log(member_farms[0], 1, deaths=40)

    o = network_service.build(coop, period="week")
    assert o.rows[0].name == "Member Farm 1"
    assert o.rows[0].status == "losing"
    assert "40 birds" in o.rows[0].attention[0]


def test_the_logging_rate_is_reported(coop, member_farms):
    """The number that decides whether any of these records are worth anything."""
    log(member_farms[0], 0)
    log(member_farms[1], 1)

    o = network_service.build(coop, period="week")
    assert o.farms_with_birds == 3
    assert o.farms_logging == 2
    assert o.logging_rate_pct == Decimal("66.7")
    assert "2 of 3 farms" in o.headline


def test_a_quiet_week_says_nothing_needs_attention(coop, member_farms):
    for f in member_farms:
        for d in range(3):
            log(f, d)

    o = network_service.build(coop, period="week")
    assert o.needs_attention == []
    assert "Nothing needs your attention" in o.headline


def test_a_farm_outside_the_cooperative_is_not_shown(coop, member_farms, broiler):
    """Membership of the cooperative is what grants sight, not proximity."""
    outsider = Farm.objects.create(name="Someone Else", state="Oyo")
    Batch.objects.create(
        farm=outsider,
        bird_type=broiler,
        name="Theirs",
        started_on=date.today(),
        stocked=100,
        cost_per_bird=Decimal("850.00"),
    )

    o = network_service.build(coop, period="week")
    assert "Someone Else" not in [r.name for r in o.rows]
    assert o.farm_count == 3


def test_an_empty_cooperative_is_not_an_error(coop):
    o = network_service.build(coop, period="week")
    assert o.farm_count == 0
    assert "No farms have joined yet." in o.headline


def test_an_officer_can_read_the_overview(coop, officer, member_farms):
    OrganisationMembership.objects.create(user=officer, organisation=coop, role="officer")
    client = APIClient()
    client.force_authenticate(officer)

    response = client.get(f"/api/v1/organisations/{coop.id}/overview/")
    assert response.status_code == 200
    assert response.data["farm_count"] == 3


def test_a_stranger_cannot_read_the_overview(coop, officer, member_farms):
    client = APIClient()
    client.force_authenticate(officer)
    assert client.get(f"/api/v1/organisations/{coop.id}/overview/").status_code == 403


def test_an_officer_cannot_write_to_a_member_farm(coop, officer, member_farms):
    """
    The promise that makes a farmer willing to join a cooperative on Aviro.

    Being an officer of the cooperative grants no standing on the farm itself.
    """
    OrganisationMembership.objects.create(user=officer, organisation=coop, role="owner")
    farm = member_farms[0]
    batch = farm.batches.first()

    client = APIClient()
    client.force_authenticate(officer)

    response = client.post(
        f"/api/v1/farms/{farm.id}/batches/{batch.id}/logs/",
        {"logged_on": str(date.today()), "feed_kg": "10", "deaths": 0},
        format="json",
    )
    assert response.status_code == 403
    assert not DailyLog.objects.filter(batch=batch).exists()


def test_an_officer_cannot_read_a_member_farm_directly_either(coop, officer, member_farms):
    """The overview is a summary by design. It is not a key to the whole book."""
    OrganisationMembership.objects.create(user=officer, organisation=coop, role="owner")
    farm = member_farms[0]

    client = APIClient()
    client.force_authenticate(officer)
    assert client.get(f"/api/v1/farms/{farm.id}/batches/").status_code == 403


def test_the_farmers_own_access_is_untouched(coop, member_farms, user):
    """Joining a cooperative must not change anything for the farmer."""
    farm = member_farms[0]
    Membership.objects.create(user=user, farm=farm, role=Membership.Role.OWNER)

    client = APIClient()
    client.force_authenticate(user)
    assert client.get(f"/api/v1/farms/{farm.id}/batches/").status_code == 200
