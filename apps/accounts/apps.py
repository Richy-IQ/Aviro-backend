from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Accounts"

    def ready(self) -> None:
        # Registers the demo-mode warning.
        from . import checks  # noqa: F401
