from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import OtpCode, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["-created_at"]
    list_display = ["phone", "display_name", "state", "phone_verified_at", "is_active"]
    list_filter = ["is_active", "is_staff", "state"]
    search_fields = ["phone", "first_name", "last_name"]
    readonly_fields = ["id", "created_at", "updated_at", "last_login", "phone_verified_at"]

    fieldsets = (
        (None, {"fields": ("id", "phone", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "state", "lga")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Dates", {"fields": ("last_login", "phone_verified_at", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),
    )


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ["phone", "created_at", "expires_at", "attempts", "consumed_at"]
    search_fields = ["phone"]
    readonly_fields = [f.name for f in OtpCode._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False
