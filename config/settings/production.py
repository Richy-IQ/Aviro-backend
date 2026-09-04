"""
Production settings.

Everything here is either a security control or a deployment concern. Reading
this file should tell you exactly how the deployed service differs from a
development one.
"""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

# No wildcard: an explicit host list is what makes the Host header check useful.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=CORS_ALLOWED_ORIGINS)

# ── Transport security ────────────────────────────────────────────────────
# The service sits behind a TLS-terminating proxy, so it must trust the
# forwarded protocol header to know a request arrived over HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)

SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

CONN_MAX_AGE = 60

# Real delivery. The provider is configured in apps.accounts.services.otp.
OTP_DELIVERY = env("OTP_DELIVERY", default="sms")
