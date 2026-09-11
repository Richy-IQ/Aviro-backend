from __future__ import annotations

from datetime import date

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import CoopInvoice, Payment
from .services import invoices as invoice_service
from .services.invoices import _next_number


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "reference", "farm", "batch", "kind", "amount", "status",
        "provider", "paid_at", "covers_until",
    ]
    list_filter = ["status", "kind", "provider", "created_at"]
    search_fields = ["reference", "farm__name", "batch__name", "paid_by__phone"]
    date_hierarchy = "created_at"
    # A payment is a record of what a provider said. Editing it by hand would
    # make it say something else.
    readonly_fields = [
        "id", "farm", "batch", "paid_by", "kind", "amount", "currency", "reference",
        "provider", "status", "paid_at", "covers_from", "covers_until",
        "provider_response", "created_at", "updated_at",
    ]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("farm", "batch", "paid_by")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(CoopInvoice)
class CoopInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "number", "organisation", "period_start", "period_end",
        "farms_count", "amount", "status", "due_on", "paid_on",
    ]
    list_filter = ["status", "organisation"]
    search_fields = ["number", "organisation__name"]
    autocomplete_fields = ["organisation"]
    readonly_fields = ["id", "number", "amount", "created_at", "updated_at"]
    actions = ["mark_sent", "mark_paid"]

    def save_model(self, request, obj, form, change):
        if not obj.number:
            obj.number = _next_number(obj.period_start.year)
        super().save_model(request, obj, form, change)

    @admin.action(description="Mark as sent to the cooperative")
    def mark_sent(self, request: HttpRequest, queryset: QuerySet) -> None:
        for invoice in queryset:
            invoice_service.mark_sent(invoice)
        self.message_user(request, f"{queryset.count()} marked as sent.")

    @admin.action(description="Mark as paid — the transfer has arrived")
    def mark_paid(self, request: HttpRequest, queryset: QuerySet) -> None:
        for invoice in queryset:
            invoice_service.mark_paid(invoice, on=date.today())
        self.message_user(
            request,
            f"{queryset.count()} marked as paid. Member farms now have the money tools.",
            messages.SUCCESS,
        )
