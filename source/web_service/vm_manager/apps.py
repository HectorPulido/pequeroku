from django.apps import AppConfig


class VmManagerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vm_manager"

    def ready(self):
        from . import signals  # noqa: F401
