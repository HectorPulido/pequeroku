from django.contrib import admin
from .models import Config, AIUsageLog, AuditLog


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    """
    Admin configuration for the Config model.
    """

    list_display = ("id", "name", "value", "description")


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "query", "created_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "user",
        "target_type",
        "target_id",
        "success",
    )
    list_filter = ("action", "success", "created_at")
    search_fields = ("message", "target_id", "user__username", "metadata")
