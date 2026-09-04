"""Startup checks for the accounts app."""

from django.conf import settings
from django.core.checks import Warning, register


@register()
def demo_mode_is_announced(app_configs, **kwargs):
    """
    Refuse to let demo mode be quiet.

    It returns sign-in codes to anyone who asks, so a deployment running it
    without someone having decided to is a serious problem. Django prints this
    on every management command and every server start.
    """
    if not getattr(settings, "OTP_DEMO_MODE", False):
        return []

    return [
        Warning(
            "OTP_DEMO_MODE is on: sign-in codes are returned in API responses.",
            hint=(
                "Anyone who knows a phone number can sign in as that person. "
                "This is for demos only — unset OTP_DEMO_MODE before real users."
            ),
            id="accounts.W001",
        )
    ]
