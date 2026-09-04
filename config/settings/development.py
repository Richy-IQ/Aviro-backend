"""Development settings. Convenience over hardening, and nothing that ships."""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, env

DEBUG = True

ALLOWED_HOSTS = ["*"]

# The Next.js dev server, on the two ports it commonly lands on.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000", "http://localhost:3002"],
)
CORS_ALLOW_CREDENTIALS = True

# Browsable API makes the endpoints explorable while the frontend is being wired.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# OTP codes are printed to the console instead of being sent, so no SMS is
# spent during development. See apps.accounts.services.otp.
OTP_DELIVERY = "console"
