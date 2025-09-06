from django.apps import AppConfig


class InternalConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "internal_config"

    def ready(self):
        from . import signals  # noqa: F401
