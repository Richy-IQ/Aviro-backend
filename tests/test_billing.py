"""
Billing.

The rules a farmer is trusting when they pay: they are charged the price they
were shown, they are never charged for days they already have, the tools unlock
only when the money has really arrived, and nothing about the birds themselves
is ever behind the paywall.
"""

import hashlib
import hmac
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.billing.models import Payment
from apps.billing.services import access, checkout, invoices
from apps.billing.services.providers import PaystackProvider
from apps.common.exceptions import DomainError
from apps.farms.models import Membership, Organisation, OrganisationMembership
from apps.flocks.models import Batch, BirdType

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_payments(settings):
    settings.PAYMENTS_PROVIDER = "fake"
    settings.BILLING_BATCH_PRICE = 2500
    settings.BILLING_MONTH_PRICE = 3000
    settings.BILLING_COOP_PRICE_PER_FARM = 4000
    settings.BILLING_GRACE_DAYS = 60
    settings.FRONTEND_URL = "https://app.example"


@pytest.fixture
def client_for(farm):
    def make(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return make


@pytest.fixture
def layer_batch(farm):
    return Batch.objects.create(
        farm=farm,
        bird_type=BirdType.objects.get(code="layer"),
        name="Layers",
        started_on=date.today() - timedelta(days=30),
        stocked=300,
        cost_per_bird=Decimal("1200.00"),
    )


def pay(batch, user):
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    return checkout.confirm(started.payment.reference)


# ── What a payment buys ─────────────────────────────────────────────────────


def test_a_broiler_batch_is_charged_once_and_covered_through_the_sale(batch):
    offer = checkout.offer_for(batch)
    assert offer.kind == Payment.Kind.BATCH
    assert offer.amount == Decimal("2500")
    assert offer.covers_from == batch.started_on
    # The full 42-day cycle, then 60 days for the bank visit after selling.
    assert offer.covers_until == batch.started_on + timedelta(days=41 + 60)


def test_a_layer_farm_is_charged_by_the_month(layer_batch):
    """Layers earn every week for a year, so a monthly charge matches the cash."""
    offer = checkout.offer_for(layer_batch)
    assert offer.kind == Payment.Kind.MONTH
    assert offer.amount == Decimal("3000")
    assert (offer.covers_until - offer.covers_from).days == 29


def test_paying_unlocks_the_money_tools(batch, user):
    assert not access.for_farm(batch.farm).active

    payment = pay(batch, user)

    assert payment.status == Payment.Status.PAID
    status = access.for_farm(batch.farm)
    assert status.active
    assert status.source == "batch"
    assert status.covered_by == batch.name


def test_a_started_but_unpaid_checkout_unlocks_nothing(batch, user):
    checkout.start(farm=batch.farm, batch=batch, user=user)
    assert not access.for_farm(batch.farm).active


def test_cover_ends_when_it_says_it_does(batch, user):
    payment = pay(batch, user)
    day_after = payment.covers_until + timedelta(days=1)
    assert access.for_farm(batch.farm, on=payment.covers_until).active
    assert not access.for_farm(batch.farm, on=day_after).active


# ── Never take money for nothing ────────────────────────────────────────────


def test_the_same_batch_cannot_be_paid_for_twice(batch, user):
    pay(batch, user)
    with pytest.raises(DomainError, match="already paid for"):
        checkout.start(farm=batch.farm, batch=batch, user=user)


def test_a_farm_its_cooperative_pays_for_is_not_charged(batch, user):
    coop = Organisation.objects.create(name="Oyo Growers")
    batch.farm.organisation = coop
    batch.farm.save()
    invoice = invoices.draft_for(coop, starts_on=date.today() - timedelta(days=1), days=365)
    invoices.mark_paid(invoice)

    with pytest.raises(DomainError, match="already covered by Oyo Growers"):
        checkout.start(farm=batch.farm, batch=batch, user=user)


def test_a_monthly_renewal_carries_on_from_the_end_of_the_last(layer_batch, user):
    """Paying early must never lose a day."""
    first = pay(layer_batch, user)
    second = pay(layer_batch, user)

    assert second.covers_from == first.covers_until + timedelta(days=1)
    assert (second.covers_until - second.covers_from).days == 29


# ── Only real money unlocks anything ────────────────────────────────────────


def test_confirming_twice_settles_once(batch, user):
    """The browser returning and the webhook arriving must not double anything."""
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    first = checkout.confirm(started.payment.reference)
    second = checkout.confirm(started.payment.reference)

    assert first.pk == second.pk
    assert Payment.objects.filter(status=Payment.Status.PAID).count() == 1


def test_a_payment_for_the_wrong_amount_unlocks_nothing(batch, user):
    """A tampered checkout must not buy a batch for one naira."""
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    cache.set(
        f"fake-payment:{started.payment.reference}", {"amount": 100, "currency": "NGN"}, 60
    )

    payment = checkout.confirm(started.payment.reference)
    assert payment.status == Payment.Status.FAILED
    assert not access.for_farm(batch.farm).active


def test_an_abandoned_payment_stays_pending(batch, user):
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    cache.delete(f"fake-payment:{started.payment.reference}")

    assert checkout.confirm(started.payment.reference).status == Payment.Status.PENDING


def test_the_farmers_phone_number_is_not_handed_to_the_provider(batch, user):
    with mock.patch("apps.billing.services.checkout.get_provider") as get:
        provider = get.return_value
        provider.name = "fake"
        provider.initialize.return_value = mock.Mock(authorization_url="https://x", reference="r")
        checkout.start(farm=batch.farm, batch=batch, user=user)

    email = provider.initialize.call_args.kwargs["email"]
    digits = user.phone.lstrip("+")
    assert digits not in email and digits[-10:] not in email


def test_receipts_can_go_to_one_inbox_before_there_is_a_domain(batch, user, settings):
    """Gmail delivers name+anything@gmail.com to name@gmail.com."""
    settings.PAYSTACK_RECEIPT_EMAIL = "aviropayments@gmail.com"
    with mock.patch("apps.billing.services.checkout.get_provider") as get:
        provider = get.return_value
        provider.name = "fake"
        provider.initialize.return_value = mock.Mock(authorization_url="https://x", reference="r")
        checkout.start(farm=batch.farm, batch=batch, user=user)

    email = provider.initialize.call_args.kwargs["email"]
    assert email == f"aviropayments+{user.id.hex}@gmail.com"
    assert user.phone.lstrip("+") not in email


def test_the_return_address_is_ours_not_the_callers(batch, user):
    """So a checkout cannot be pointed at someone else's site."""
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    assert started.authorization_url.startswith("https://app.example/billing/done?")


# ── The paywall itself ──────────────────────────────────────────────────────


def test_the_statement_is_paid_for(batch, user, client_for):
    client = client_for(user)
    url = f"/api/v1/farms/{batch.farm.id}/statement/"

    refused = client.get(url)
    assert refused.status_code == 402
    assert refused.data["error"]["code"] == "payment_required"

    pay(batch, user)
    assert client.get(url).status_code == 200


def test_the_downloads_are_paid_for(batch, user, client_for):
    client = client_for(user)
    url = f"/api/v1/farms/{batch.farm.id}/records/?dataset=logs"
    assert client.get(url).status_code == 402
    pay(batch, user)
    assert client.get(url).status_code == 200


def test_the_weekly_report_stays_free_and_the_monthly_does_not(batch, user, client_for):
    """The week is mostly deaths and doses due — the birds' welfare, never paywalled."""
    client = client_for(user)
    base = f"/api/v1/farms/{batch.farm.id}/summary/"
    assert client.get(f"{base}?period=week").status_code == 200
    assert client.get(f"{base}?period=month").status_code == 402


def test_the_birds_are_never_behind_the_paywall(batch, user, client_for):
    """Plan, today's target, logging and the warning signs, on an unpaid farm."""
    client = client_for(user)
    farm, b = batch.farm, batch
    assert client.get(f"/api/v1/farms/{farm.id}/batches/{b.id}/plan/").status_code == 200
    assert client.get(f"/api/v1/farms/{farm.id}/batches/{b.id}/today/").status_code == 200
    assert client.get(f"/api/v1/farms/{farm.id}/alerts/").status_code == 200
    logged = client.post(
        f"/api/v1/farms/{farm.id}/batches/{b.id}/logs/",
        {"logged_on": str(date.today()), "feed_kg": "20", "deaths": 1},
        format="json",
    )
    assert logged.status_code in (200, 201)


# ── Who can pay ─────────────────────────────────────────────────────────────


def test_only_an_owner_or_manager_can_spend_the_farms_money(batch, client_for, django_user_model):
    attendant = django_user_model.objects.create_user(phone="08011112222")
    Membership.objects.create(user=attendant, farm=batch.farm, role=Membership.Role.ATTENDANT)

    response = client_for(attendant).post(
        f"/api/v1/farms/{batch.farm.id}/batches/{batch.id}/checkout/"
    )
    assert response.status_code == 403
    assert not Payment.objects.exists()


def test_the_owner_can_start_a_checkout(batch, user, client_for):
    response = client_for(user).post(
        f"/api/v1/farms/{batch.farm.id}/batches/{batch.id}/checkout/"
    )
    assert response.status_code == 201
    assert "reference=" in response.data["authorization_url"]


def test_a_stranger_cannot_confirm_someone_elses_payment(
    batch, user, client_for, django_user_model
):
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    stranger = django_user_model.objects.create_user(phone="08033334444")

    response = client_for(stranger).post(
        "/api/v1/billing/confirm/", {"reference": started.payment.reference}, format="json"
    )
    assert response.status_code == 422
    assert Payment.objects.get().status == Payment.Status.PENDING


# ── The webhook ─────────────────────────────────────────────────────────────


def _signed(body: bytes, key: str) -> str:
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


def test_an_unsigned_webhook_is_refused(batch, user, settings):
    """Otherwise anyone could post "charge succeeded" and unlock a farm for free."""
    settings.PAYSTACK_SECRET_KEY = "sk_test_secret"
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    body = json.dumps(
        {"event": "charge.success", "data": {"reference": started.payment.reference}}
    ).encode()

    response = APIClient().post(
        "/api/v1/billing/paystack/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="forged",
    )
    assert response.status_code == 400
    assert Payment.objects.get().status == Payment.Status.PENDING


def test_a_signed_webhook_settles_the_payment(batch, user, settings):
    settings.PAYSTACK_SECRET_KEY = "sk_test_secret"
    started = checkout.start(farm=batch.farm, batch=batch, user=user)
    body = json.dumps(
        {"event": "charge.success", "data": {"reference": started.payment.reference}}
    ).encode()

    response = APIClient().post(
        "/api/v1/billing/paystack/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=_signed(body, "sk_test_secret"),
    )
    assert response.status_code == 200
    assert Payment.objects.get().status == Payment.Status.PAID


# ── Cooperatives ────────────────────────────────────────────────────────────


def test_an_invoice_is_priced_from_its_membership(farm):
    coop = Organisation.objects.create(name="Oyo Growers")
    farm.organisation = coop
    farm.save()

    invoice = invoices.draft_for(coop)
    assert invoice.farms_count == 1
    assert invoice.amount == Decimal("4000.00")
    assert invoice.number.startswith(f"AV-{date.today().year}-")
    assert invoices.draft_for(coop).number > invoice.number


def test_only_a_paid_invoice_covers_member_farms(farm):
    coop = Organisation.objects.create(name="Oyo Growers")
    farm.organisation = coop
    farm.save()

    invoice = invoices.draft_for(coop)
    assert not access.for_farm(farm).active

    invoices.mark_sent(invoice)
    assert not access.for_farm(farm).active

    invoices.mark_paid(invoice)
    status = access.for_farm(farm)
    assert status.active and status.source == "cooperative"
    assert status.covered_by == "Oyo Growers"


def test_an_officer_sees_sent_invoices_but_not_drafts(client_for, django_user_model):
    coop = Organisation.objects.create(name="Oyo Growers")
    officer = django_user_model.objects.create_user(phone="08055556666")
    OrganisationMembership.objects.create(user=officer, organisation=coop)

    invoices.draft_for(coop)
    invoices.mark_sent(invoices.draft_for(coop))

    response = client_for(officer).get(f"/api/v1/organisations/{coop.id}/invoices/")
    assert response.status_code == 200
    assert [i["status"] for i in response.data] == ["sent"]


def test_a_stranger_cannot_read_a_cooperatives_invoices(client_for, user):
    coop = Organisation.objects.create(name="Oyo Growers")
    response = client_for(user).get(f"/api/v1/organisations/{coop.id}/invoices/")
    assert response.status_code == 403


# ── Paystack itself ─────────────────────────────────────────────────────────


def _paystack_reply(payload: dict):
    reply = mock.MagicMock()
    reply.read.return_value = json.dumps(payload).encode()
    reply.__enter__.return_value = reply
    return reply


def test_paystack_is_asked_for_card_bank_and_ussd():
    """Plenty of farmers have a bank account and a phone, and no card."""
    reply = _paystack_reply(
        {"status": True, "data": {"authorization_url": "https://paystack/abc", "reference": "R1"}}
    )
    with mock.patch("urllib.request.urlopen", return_value=reply) as urlopen:
        result = PaystackProvider("sk_test").initialize(
            email="a@b.c", amount_kobo=250000, reference="R1", callback_url="https://x", metadata={}
        )

    sent = json.loads(urlopen.call_args.args[0].data)
    assert sent["amount"] == 250000
    assert {"card", "bank", "ussd", "bank_transfer"} <= set(sent["channels"])
    assert result.authorization_url == "https://paystack/abc"


def test_a_paystack_verification_is_read_correctly():
    reply = _paystack_reply(
        {"status": True, "data": {"status": "success", "amount": 250000, "currency": "NGN"}}
    )
    with mock.patch("urllib.request.urlopen", return_value=reply):
        result = PaystackProvider("sk_test").verify("R1")
    assert result.succeeded
    assert result.amount_kobo == 250000


# ── When Paystack says no ───────────────────────────────────────────────────


def _http_error(code: int, message: str):
    import io
    import urllib.error

    return urllib.error.HTTPError(
        url="https://api.paystack.co/transaction/initialize",
        code=code,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(json.dumps({"status": False, "message": message}).encode()),
    )


def test_paystacks_reason_is_kept_not_swallowed(batch, user, settings):
    """
    Paystack refuses with a 4xx and says why. That reason is the diagnosis:
    it is kept on the failed payment for the admin, not shown to the farmer.
    """
    from apps.billing.services.providers import ProviderUnavailable

    settings.PAYMENTS_PROVIDER = "paystack"
    settings.PAYSTACK_SECRET_KEY = "sk_test_abc"
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(401, "Invalid key")):
        with pytest.raises(ProviderUnavailable) as raised:
            checkout.start(farm=batch.farm, batch=batch, user=user)

    assert "Invalid key" not in str(raised.value.detail)
    payment = Payment.objects.get()
    assert payment.status == Payment.Status.FAILED
    assert payment.provider_response == {"stage": "start", "error": "HTTP 401: Invalid key"}


def test_an_attempt_that_never_reached_paystack_is_not_in_the_farmers_history(
    batch, user, settings, client_for
):
    """"Failed ₦2,500" would read as money gone when none moved."""
    from apps.billing.services.providers import ProviderUnavailable

    settings.PAYMENTS_PROVIDER = "paystack"
    settings.PAYSTACK_SECRET_KEY = "sk_test_abc"
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(400, "Invalid email")):
        with pytest.raises(ProviderUnavailable):
            checkout.start(farm=batch.farm, batch=batch, user=user)

    response = client_for(user).get(f"/api/v1/farms/{batch.farm.id}/billing/")
    assert response.data["payments"] == []


def test_a_key_pasted_with_whitespace_or_quotes_still_works():
    from apps.billing.services.providers import clean_key

    assert clean_key("  sk_test_abc\n") == "sk_test_abc"
    assert clean_key('"sk_test_abc"') == "sk_test_abc"
    assert PaystackProvider(" sk_test_abc \n").secret_key == "sk_test_abc"


def test_the_public_key_pasted_by_mistake_is_flagged(settings):
    from apps.billing.checks import payments_are_configured

    settings.PAYMENTS_PROVIDER = "paystack"
    settings.PAYSTACK_SECRET_KEY = "pk_test_abc"
    ids = [w.id for w in payments_are_configured(None)]
    assert "billing.W003" in ids

