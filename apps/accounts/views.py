"""
Authentication endpoints.

APIView throughout: each endpoint does one thing, and the flow is readable
top to bottom without knowing what a router generated.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OtpCode
from .phone import mask
from .serializers import OtpRequestSerializer, OtpVerifySerializer, UserSerializer
from .services import otp as otp_service


class RequestCodeView(APIView):
    """
    POST /api/v1/auth/request-code/

    Sends a 6-digit code to the number. Responds identically whether or not an
    account exists, so the endpoint cannot be used to discover which numbers
    are registered.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_request"

    def post(self, request: Request) -> Response:
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]

        _, plaintext = otp_service.request_code(phone)

        body = {
            "sent_to": mask(phone),
            "expires_in_seconds": int(OtpCode.LIFETIME.total_seconds()),
        }

        # Demo mode hands the code back so a tester can read it off the screen.
        # The response says so in as many words, because a client that shows a
        # code without saying why teaches people to expect it.
        if getattr(settings, "OTP_DEMO_MODE", False):
            body["demo_code"] = plaintext
            body["demo_notice"] = (
                "Demo mode: this code is shown because phone verification is "
                "switched off. Do not use this build with real farmers."
            )

        return Response(body, status=status.HTTP_202_ACCEPTED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class VerifyCodeView(APIView):
    """
    POST /api/v1/auth/verify-code/

    Exchanges a valid code for a token pair. Creates the account on first
    successful verification — there is no separate registration step.

    Deliberately outside ATOMIC_REQUESTS. A failed attempt has to be recorded
    even though the request ends in an error: inside the request transaction
    the increment would be rolled back with it, the attempt counter would never
    rise, and a six-digit code could be guessed without limit.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_verify"

    def post(self, request: Request) -> Response:
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = otp_service.verify_code(
            serializer.validated_data["phone"],
            serializer.validated_data["code"],
        )
        if not result.ok:
            # Returned rather than raised, so the recorded attempt survives.
            return Response(
                {"error": {"code": result.code, "message": result.message}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        refresh = RefreshToken.for_user(result.user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "is_new_account": result.created,
                "user": UserSerializer(result.user).data,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class CurrentUserView(APIView):
    """
    GET  /api/v1/auth/me/  — the signed-in user.
    PATCH /api/v1/auth/me/ — update the fields collected after sign-up, such as
    name and location, which are asked on the screens where they matter.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
