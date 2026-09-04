"""
A single error shape for the whole API.

DRF's default responses vary by exception type — sometimes a dict of field
errors, sometimes a bare "detail" string. Clients then need branching logic to
show a message. Normalising once here means the frontend can always read
`error.message` and, for form errors, `error.fields`.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class DomainError(exceptions.APIException):
    """
    A rule of the business was broken, not a rule of HTTP.

    Raised from the service layer — "you cannot log a day before the batch
    started", "this batch is already closed" — and rendered as a 422 so a
    client can tell it apart from a malformed request.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "That action is not allowed for this record."
    default_code = "domain_error"


def _message_from(detail: Any) -> str:
    """Reduce DRF's nested detail structures to one human sentence."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        return _message_from(detail[0])
    if isinstance(detail, dict):
        for value in detail.values():
            return _message_from(value)
    return "Something went wrong."


def _fields_from(detail: Any) -> dict[str, list[str]] | None:
    """
    Per-field messages, when the exception carries them.

    DRF puts non-field errors under "detail", which is not a form field — a
    client rendering it beside an input would label the wrong thing.
    """
    if not isinstance(detail, dict):
        return None
    fields: dict[str, list[str]] = {}
    for key, value in detail.items():
        if key == "detail":
            continue
        fields[key] = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    return fields or None


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Render every handled exception in one consistent envelope."""
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        exc = exceptions.ValidationError(detail=detail)
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled: let Django's 500 machinery deal with it, but make sure the
        # traceback reaches the logs with the request attached.
        logger.exception("Unhandled exception in %s", context.get("view"))
        return None

    code = getattr(exc, "default_code", "error")
    if isinstance(exc, exceptions.APIException) and isinstance(exc.detail, dict):
        code = getattr(exc, "default_code", "invalid")

    fields = _fields_from(response.data)
    response.data = {
        "error": {
            "code": code,
            "message": _message_from(response.data),
            **({"fields": fields} if fields else {}),
        }
    }
    return response
