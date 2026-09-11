"""Startup checks for billing: say out loud when payments cannot work."""

from django.conf import settings
from django.core.checks import Warning, register

from .services.providers import clean_key


@register()
def payments_are_configured(app_configs, **kwargs):
    if settings.PAYMENTS_PROVIDER != "paystack":
        return []

    problems = []
    key = clean_key(settings.PAYSTACK_SECRET_KEY)
    if key and not key.startswith(("sk_test_", "sk_live_")):
        problems.append(
            Warning(
                "PAYSTACK_SECRET_KEY does not look like a Paystack secret key.",
                hint=(
                    "It should start with sk_test_ or sk_live_. A key starting pk_ is the "
                    "public key, which Paystack refuses for this."
                ),
                id="billing.W003",
            )
        )
    if not key:
        problems.append(
            Warning(
                "PAYSTACK_SECRET_KEY is not set: nobody can pay, and webhooks are rejected.",
                hint="Set it from the Paystack dashboard. Use the test key until launch.",
                id="billing.W001",
            )
        )
    if not settings.PAYSTACK_RECEIPT_EMAIL and settings.PAYSTACK_EMAIL_DOMAIN.endswith(".invalid"):
        problems.append(
            Warning(
                "No receipt address is set: payment receipts go nowhere.",
                hint=(
                    "Set PAYSTACK_RECEIPT_EMAIL to an inbox you own (a Gmail address works), "
                    "or PAYSTACK_EMAIL_DOMAIN to a domain you own."
                ),
                id="billing.W002",
            )
        )
    return problems
