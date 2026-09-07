"""Admin for farms, pens and who may act on them."""

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import Farm, Membership, Organisation, OrganisationMembership, Pen


class PenInline(admin.TabularInline):
    model = Pen
    extra = 0
    fields = ["name"]
    show_change_link = True


class MembershipInline(admin.TabularInline):
    model = Membership
    fk_name = "farm"
    extra = 0
    fields = ["user", "role", "accepted_at"]
    autocomplete_fields = ["user"]
    readonly_fields = ["accepted_at"]
    show_change_link = True


@admin.register(Farm)
class FarmAdmin(admin.ModelAdmin):
    list_display = ["name", "location", "member_count", "batch_count", "created_at"]
    list_filter = ["state", "created_at"]
    search_fields = ["name", "state", "lga", "memberships__user__phone"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [PenInline, MembershipInline]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("id", "name")}),
        ("Location", {"fields": ("state", "lga")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        # Counted in the query rather than per row, so the list stays one trip.
        return (
            super()
            .get_queryset(request)
            .annotate(_members=Count("memberships", distinct=True))
            .annotate(_batches=Count("batches", distinct=True))
        )

    @admin.display(description="Members", ordering="_members")
    def member_count(self, farm: Farm) -> int:
        return farm._members

    @admin.display(description="Batches", ordering="_batches")
    def batch_count(self, farm: Farm) -> int:
        return farm._batches


@admin.register(Pen)
class PenAdmin(admin.ModelAdmin):
    list_display = ["name", "farm", "batch_count"]
    list_filter = ["farm"]
    search_fields = ["name", "farm__name"]
    autocomplete_fields = ["farm"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("farm").annotate(
            _batches=Count("batches")
        )

    @admin.display(description="Batches", ordering="_batches")
    def batch_count(self, pen: Pen) -> int:
        return pen._batches


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user_phone", "user_name", "farm", "role_badge", "pen_scope", "accepted_at"]
    list_filter = ["role", "farm", "accepted_at"]
    search_fields = ["user__phone", "user__first_name", "user__last_name", "farm__name"]
    autocomplete_fields = ["user", "farm", "invited_by"]
    filter_horizontal = ["pens"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related("user", "farm").prefetch_related("pens")

    @admin.display(description="Phone", ordering="user__phone")
    def user_phone(self, m: Membership) -> str:
        return m.user.phone

    @admin.display(description="Name")
    def user_name(self, m: Membership) -> str:
        return m.user.display_name or "—"

    @admin.display(description="Role", ordering="role")
    def role_badge(self, m: Membership) -> str:
        # Owners can do anything; viewers can do nothing. Worth seeing at a glance.
        colour = {"owner": "#0F766E", "manager": "#F97316", "attendant": "#3B82F6"}.get(
            m.role, "#94A3B8"
        )
        return format_html(
            '<span style="color:{};font-weight:500">{}</span>', colour, m.get_role_display()
        )

    @admin.display(description="Pens")
    def pen_scope(self, m: Membership) -> str:
        pens = list(m.pens.all())
        return ", ".join(p.name for p in pens) if pens else "Whole farm"


class FarmInline(admin.TabularInline):
    model = Farm
    fields = ["name", "state", "lga"]
    extra = 0
    show_change_link = True


class OrganisationMembershipInline(admin.TabularInline):
    model = OrganisationMembership
    autocomplete_fields = ["user"]
    extra = 0


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "state", "lga", "farm_count"]
    list_filter = ["kind", "state"]
    search_fields = ["name", "state", "lga"]
    inlines = [OrganisationMembershipInline, FarmInline]
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).annotate(_farms=Count("farms"))

    @admin.display(description="Farms", ordering="_farms")
    def farm_count(self, obj) -> int:
        return obj._farms


@admin.register(OrganisationMembership)
class OrganisationMembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organisation", "role", "created_at"]
    list_filter = ["role", "organisation"]
    search_fields = ["user__phone", "user__first_name", "organisation__name"]
    autocomplete_fields = ["user", "organisation"]
    readonly_fields = ["id", "created_at", "updated_at"]
