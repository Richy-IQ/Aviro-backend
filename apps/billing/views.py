"""
Billing endpoints.

Checkout and confirmation for farmers, a webhook for Paystack, and invoices for
cooperatives. Views stay thin; the rules are in services/.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError
from apps.farms.models import Farm, Organisation
from apps.farms.permissions import IsFarmMember, IsOrganisationMember, membership_for
from apps.flocks.models import Batch

from .models import CoopInvoice, Payment
from .serializers import (
    ALWAYS_FREE,
    INCLUDED,
    AccessSerializer,
    CoopInvoiceSerializer,
    OfferSerializer,
    PaymentSerializer,
)
from .services import access, checkout
from .services.providers import signature_is_valid

logger = logging.getLogger(__name__)


class FarmBillingView(APIView):
    """
    GET /api/v1/farms/<farm_id>/billing/

    Whether the farm has the money tools, until when and why, what unlocking
    them for the current batch would cost, and every payment made.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        farm = self.get_farm()
        current = (
            Batch.objects.filter(farm=farm, status=Batch.Status.ACTIVE)
            .select_related("bird_type", "farm")
            .order_by("-started_on")
            .first()
        )
        offer = checkout.offer_for(current) if current else None

        return Response(
            {
                "access": AccessSerializer(access.for_farm(farm)).data,
                "offer": OfferSerializer(offer).data if offer else None,
                "offer_batch": {"id": str(current.id), "name": current.name} if current else None,
                "prices": {
                    "batch": settings.BILLING_BATCH_PRICE,
                    "month": settings.BILLING_MONTH_PRICE,
                },
                "included": INCLUDED,
                "always_free": ALWAYS_FREE,
                "payments": PaymentSerializer(
                    farm.payments.select_related("batch").exclude(
                        status=Payment.Status.PENDING
                    ),
                    many=True,
                ).data,
                "can_pay": request.membership.can_manage_team,
            }
        )


class BatchCheckoutView(APIView):
    """
    POST /api/v1/farms/<farm_id>/batches/<batch_id>/checkout/

    Start paying for the money tools on one batch. Returns the page to send the
    farmer to. Only an owner or manager can spend the farm's money.
    """

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def post(self, request: Request, farm_id, batch_id) -> Response:
        farm = self.get_farm()
        if not request.membership.can_manage_team:
            raise PermissionDenied("Only the farm owner or a manager can pay.")

        batch = get_object_or_404(
            Batch.objects.select_related("bird_type", "farm"), pk=batch_id, farm=farm
        )
        started = checkout.start(farm=farm, batch=batch, user=request.user)
        return Response(
            {
                "authorization_url": started.authorization_url,
                "reference": started.payment.reference,
            },
            status=status.HTTP_201_CREATED,
        )


class ConfirmPaymentView(APIView):
    """
    POST /api/v1/billing/confirm/  {"reference": "..."}

    Called when the farmer comes back from the payment page. Asks the provider
    what happened rather than believing the browser.
    """

    def post(self, request: Request) -> Response:
        reference = str(request.data.get("reference", "")).strip()
        if not reference:
            raise DomainError("A payment reference is required.")

        payment = Payment.objects.filter(reference=reference).select_related("farm").first()
        # Unknown and not-yours read the same, so references cannot be probed.
        if payment is None or membership_for(request.user, payment.farm) is None:
            raise DomainError("We have no record of that payment.")

        payment = checkout.confirm(reference)
        return Response(
            {
                "payment": PaymentSerializer(payment).data,
                "access": AccessSerializer(access.for_farm(payment.farm)).data,
            }
        )


class PaystackWebhookView(APIView):
    """
    POST /api/v1/billing/paystack/webhook/

    Paystack's word that a charge went through, for the farmer who paid and
    closed the page before coming back. Signed, and even then only used as a
    prompt: the payment is settled by verifying it with Paystack directly.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        body = request.body
        if not signature_is_valid(body, request.headers.get("x-paystack-signature")):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            event = json.loads(body)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event.get("event") == "charge.success":
            reference = (event.get("data") or {}).get("reference")
            if reference and Payment.objects.filter(reference=reference).exists():
                checkout.confirm(reference)
            else:
                logger.warning("Paystack webhook for unknown reference %s", reference)

        # Acknowledged whatever it was, so Paystack stops retrying.
        return Response(status=status.HTTP_200_OK)


class OrganisationInvoicesView(APIView):
    """GET /api/v1/organisations/<organisation_id>/invoices/"""

    permission_classes = [IsOrganisationMember]

    def get_organisation(self) -> Organisation:
        return get_object_or_404(Organisation, pk=self.kwargs["organisation_id"])

    def get(self, request: Request, organisation_id) -> Response:
        organisation = self.get_organisation()
        invoices = organisation.invoices.exclude(status=CoopInvoice.Status.DRAFT)
        return Response(CoopInvoiceSerializer(invoices, many=True).data)


class OrganisationInvoiceDetailView(APIView):
    """GET /api/v1/organisations/<organisation_id>/invoices/<invoice_id>/"""

    permission_classes = [IsOrganisationMember]

    def get_organisation(self) -> Organisation:
        return get_object_or_404(Organisation, pk=self.kwargs["organisation_id"])

    def get(self, request: Request, organisation_id, invoice_id) -> Response:
        organisation = self.get_organisation()
        invoice = get_object_or_404(
            organisation.invoices.exclude(status=CoopInvoice.Status.DRAFT), pk=invoice_id
        )
        return Response(CoopInvoiceSerializer(invoice).data)
