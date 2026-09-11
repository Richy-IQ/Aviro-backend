from django.urls import path

from .views import (
    BatchCheckoutView,
    ConfirmPaymentView,
    FarmBillingView,
    OrganisationInvoiceDetailView,
    OrganisationInvoicesView,
    PaystackWebhookView,
)

app_name = "billing"

urlpatterns = [
    path("farms/<uuid:farm_id>/billing/", FarmBillingView.as_view(), name="farm-billing"),
    path(
        "farms/<uuid:farm_id>/batches/<uuid:batch_id>/checkout/",
        BatchCheckoutView.as_view(),
        name="checkout",
    ),
    path("billing/confirm/", ConfirmPaymentView.as_view(), name="confirm"),
    path("billing/paystack/webhook/", PaystackWebhookView.as_view(), name="paystack-webhook"),
    path(
        "organisations/<uuid:organisation_id>/invoices/",
        OrganisationInvoicesView.as_view(),
        name="invoices",
    ),
    path(
        "organisations/<uuid:organisation_id>/invoices/<uuid:invoice_id>/",
        OrganisationInvoiceDetailView.as_view(),
        name="invoice-detail",
    ),
]
