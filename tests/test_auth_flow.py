"""Signing in: two screens for the farmer, two endpoints here."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import OtpCode, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _request_code(client, phone="08034129087"):
    return client.post(reverse("accounts:request-code"), {"phone": phone}, format="json")


def test_requesting_a_code_never_reveals_whether_the_number_is_registered(client):
    """Otherwise the endpoint becomes a way to enumerate Aviro's farmers."""
    unknown = _request_code(client, "08099999999")
    User.objects.create_user(phone="08088888888")
    known = _request_code(client, "08088888888")

    assert unknown.status_code == known.status_code == 202
    assert set(unknown.data) == set(known.data)


def test_verifying_a_correct_code_creates_the_account_on_first_use(client):
    _request_code(client)
    _, code = OtpCode.issue("+2348034129087")

    response = client.post(
        reverse("accounts:verify-code"),
        {"phone": "08034129087", "code": code},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["is_new_account"] is True
    assert "access" in response.data
    assert User.objects.filter(phone="+2348034129087").exists()


def test_a_returning_farmer_is_not_a_new_account(client):
    User.objects.create_user(phone="08034129087")
    _, code = OtpCode.issue("+2348034129087")

    response = client.post(
        reverse("accounts:verify-code"),
        {"phone": "08034129087", "code": code},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["is_new_account"] is False


def test_a_wrong_code_is_refused_and_counted(client):
    otp, _ = OtpCode.issue("+2348034129087")

    response = client.post(
        reverse("accounts:verify-code"),
        {"phone": "08034129087", "code": "000000"},
        format="json",
    )

    assert response.status_code == 422
    assert response.data["error"]["code"] == "otp_invalid"
    otp.refresh_from_db()
    assert otp.attempts == 1


def test_a_code_cannot_be_used_twice(client):
    _, code = OtpCode.issue("+2348034129087")
    payload = {"phone": "08034129087", "code": code}

    assert client.post(reverse("accounts:verify-code"), payload, format="json").status_code == 201
    second = client.post(reverse("accounts:verify-code"), payload, format="json")
    assert second.status_code == 422


def test_the_code_is_never_stored_in_the_clear():
    """Read access to the database must not be enough to sign in as a farmer."""
    otp, code = OtpCode.issue("+2348034129087")
    assert code not in otp.code_hash
    assert otp.code_hash.startswith("pbkdf2_")


def test_the_code_is_not_in_the_response_by_default(client, settings):
    """
    The default must be safe. A build that hands out sign-in codes has no
    phone verification at all.
    """
    settings.OTP_DEMO_MODE = False
    response = _request_code(client)

    assert response.status_code == 202
    assert "demo_code" not in response.data
    assert "demo_notice" not in response.data


def test_demo_mode_returns_the_code_and_says_why(client, settings):
    settings.OTP_DEMO_MODE = True
    response = _request_code(client)

    assert response.status_code == 202
    assert response.data["demo_code"].isdigit()
    assert len(response.data["demo_code"]) == OtpCode.LENGTH
    # The notice is part of the contract: a code shown without explanation
    # teaches testers to expect one.
    assert "Demo mode" in response.data["demo_notice"]


def test_a_demo_code_actually_works(client, settings):
    """The echoed code must be the real one, or the demo is a lie."""
    settings.OTP_DEMO_MODE = True
    response = _request_code(client)
    assert response.status_code == 202, response.data
    code = response.data["demo_code"]

    verify = client.post(
        reverse("accounts:verify-code"),
        {"phone": "08034129087", "code": code},
        format="json",
    )
    assert verify.status_code == 201
