"""
Admin for birds, batches and the daily record.

The batch page carries its derived metrics as read-only fields: they are the
numbers anyone looking at a batch actually wants, and computing them here means
support can answer "what is this farm seeing?" without running the app.
"""


from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import Batch, BirdType, Breed, DailyLog, Sale, VaccinationSchedule
from .services import metrics as metrics_service


class VaccinationScheduleInline(admin.TabularInline):
    model = VaccinationSchedule
    extra = 0
    fields = ["day", "name", "route", "notes"]
    ordering = ["day"]


class BreedInline(admin.TabularInline):
    model = Breed
    extra = 0
    fields = ["name"]


@admin.register(BirdType)
class BirdTypeAdmin(admin.ModelAdmin):
    list_display = ["label", "code", "cycle_days", "cycle_goal", "breed_count", "dose_count"]
    search_fields = ["code", "label", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [BreedInline, VaccinationScheduleInline]

    fieldsets = (
        (None, {"fields": ("id", "code", "label", "description")}),
        (
            "Cycle",
            {
                "fields": ("cycle_days", "cycle_goal"),
                "description": (
                    "Cycle length belongs to the bird, not the batch: a broiler finishes "
                    "in 42 days, a layer rears for 140 before her first egg."
                ),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .annotate(_breeds=Count("breeds", distinct=True))
            .annotate(_doses=Count("vaccination_schedule", distinct=True))
        )

    @admin.display(description="Breeds", ordering="_breeds")
    def breed_count(self, t: BirdType) -> int:
        return t._breeds

    @admin.display(description="Vaccine doses", ordering="_doses")
    def dose_count(self, t: BirdType) -> int:
        return t._doses


@admin.register(Breed)
class BreedAdmin(admin.ModelAdmin):
    list_display = ["name", "bird_type", "batch_count"]
    list_filter = ["bird_type"]
    search_fields = ["name"]
    autocomplete_fields = ["bird_type"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("bird_type").annotate(
            _batches=Count("batches")
        )

    @admin.display(description="Batches", ordering="_batches")
    def batch_count(self, b: Breed) -> int:
        return b._batches


@admin.register(VaccinationSchedule)
class VaccinationScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "bird_type", "day", "route"]
    list_filter = ["bird_type", "route"]
    search_fields = ["name", "route", "notes"]
    autocomplete_fields = ["bird_type"]
    ordering = ["bird_type", "day"]


class DailyLogInline(admin.TabularInline):
    """
    The cycle's daily record, most recent first.

    Not sliced: an inline's queryset is filtered again by the formset, and a
    sliced queryset cannot be filtered — doing so raises and takes the whole
    batch page down. Use the Daily logs list with its filters to narrow a long
    cycle instead.
    """

    model = DailyLog
    extra = 0
    fields = ["logged_on", "feed_kg", "deaths", "death_cause", "health_activity", "note"]
    ordering = ["-logged_on"]
    show_change_link = True


class SaleInline(admin.TabularInline):
    model = Sale
    extra = 0
    fields = ["sold_on", "kind", "birds", "average_weight_kg", "revenue", "buyer_name"]
    show_change_link = True


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = [
        "name", "farm", "bird_type", "breed", "started_on", "stocked",
        "logged_days", "status_badge",
    ]
    list_filter = ["status", "bird_type", "started_on", "farm"]
    search_fields = ["name", "farm__name", "breed__name", "supplier", "pen__name"]
    autocomplete_fields = ["farm", "pen", "bird_type", "breed"]
    date_hierarchy = "started_on"
    inlines = [DailyLogInline, SaleInline]

    readonly_fields = ["id", "created_at", "updated_at", "derived_metrics"]

    fieldsets = (
        (None, {"fields": ("id", "name", "farm", "pen", "status", "closed_on")}),
        ("Birds", {"fields": ("bird_type", "breed", "stocked", "started_on", "supplier")}),
        ("Cost at stocking", {"fields": ("cost_per_bird", "transport_cost")}),
        (
            "Derived figures",
            {
                "fields": ("derived_metrics",),
                "description": (
                    "Computed from the daily logs on every view, never stored — so a "
                    "corrected log corrects these too."
                ),
            },
        ),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .select_related("farm", "bird_type", "breed", "pen")
            .annotate(_logs=Count("logs", distinct=True))
        )

    @admin.display(description="Days logged", ordering="_logs")
    def logged_days(self, batch: Batch) -> int:
        return batch._logs

    @admin.display(description="Status", ordering="status")
    def status_badge(self, batch: Batch) -> str:
        colour = "#0F766E" if batch.status == Batch.Status.ACTIVE else "#94A3B8"
        return format_html(
            '<span style="color:{};font-weight:500">{}</span>', colour, batch.get_status_display()
        )

    @admin.display(description="Metrics")
    def derived_metrics(self, batch: Batch) -> str:
        """The same figures the farmer sees, computed the same way."""
        if not batch.pk:
            return "—"

        m = metrics_service.compute(batch)
        rows = [
            ("Day in cycle", f"{m.day_in_cycle} of {m.cycle_days}"),
            ("Alive", f"{m.alive:,}"),
            ("Deaths", f"{m.deaths:,} ({m.mortality_pct}%)"),
            ("Earning birds", f"{m.earning_birds:,}"),
            ("Feed to date", f"{m.total_feed_kg} kg"),
            ("Total cost", f"₦{m.total_cost:,.2f}"),
            ("Cost per bird", f"₦{m.cost_per_bird:,.2f}"),
            ("Average weight", f"{m.average_weight_kg} kg" if m.average_weight_kg else "unknown"),
            (
                "Feed conversion",
                str(m.feed_conversion) if m.feed_conversion else "not yet meaningful",
            ),
            (
                "Projected profit",
                f"₦{m.projected_profit:,.2f}" if m.projected_profit is not None else "—",
            ),
            (
                "Best day to sell",
                f"day {m.optimal_sell_day}"
                + ("" if m.sell_window_peaks else " (profit still rising — not a true peak)")
                if m.optimal_sell_day
                else "—",
            ),
            ("Logged today", "yes" if m.logged_today else "no"),
            ("Streak", f"{m.streak_days} days"),
        ]
        cells = "".join(
            f'<tr><th style="text-align:left;padding:2px 16px 2px 0;font-weight:500">{k}</th>'
            f"<td style='padding:2px 0'>{v}</td></tr>"
            for k, v in rows
        )
        return format_html('<table style="border:0">{}</table>', format_html(cells))


@admin.register(DailyLog)
class DailyLogAdmin(admin.ModelAdmin):
    list_display = [
        "logged_on", "batch", "day_in_cycle", "feed_kg", "deaths",
        "death_cause", "health_activity", "day_cost",
    ]
    list_filter = ["logged_on", "death_cause", "health_activity", "batch__farm"]
    search_fields = ["batch__name", "batch__farm__name", "note"]
    autocomplete_fields = ["batch"]
    date_hierarchy = "logged_on"
    readonly_fields = ["id", "day_in_cycle", "total_cost", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("batch", "batch__farm")

    @admin.display(description="Day")
    def day_in_cycle(self, log: DailyLog) -> int:
        return log.day_in_cycle

    @admin.display(description="Cost")
    def day_cost(self, log: DailyLog) -> str:
        return f"₦{log.total_cost:,.2f}"


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        "sold_on", "batch", "kind", "birds", "average_weight_kg", "revenue_naira",
        "per_kg", "buyer_name",
    ]
    list_filter = ["kind", "buyer_type", "sold_on", "batch__farm"]
    search_fields = ["batch__name", "batch__farm__name", "buyer_name", "note"]
    autocomplete_fields = ["batch"]
    date_hierarchy = "sold_on"
    readonly_fields = ["id", "price_per_kg", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("batch", "batch__farm")

    @admin.display(description="Revenue", ordering="revenue")
    def revenue_naira(self, sale: Sale) -> str:
        return f"₦{sale.revenue:,.2f}"

    @admin.display(description="₦/kg")
    def per_kg(self, sale: Sale) -> str:
        rate = sale.price_per_kg
        return f"₦{rate:,.2f}" if rate else "—"
