from django.contrib import admin
from .models import Config, AIUsageLog, AuditLog, AIMemory


@admin.register(AIMemory)
class AIMemoryAdmin(admin.ModelAdmin):
    list_display = ("user", "container")


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    """
    Admin configuration for the Config model.
    """

    list_display = ("id", "name", "value", "description")


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "query",
        "created_at",
        "prompt_tokens",
        "completion_tokens",
        "total_cost",
    )
    readonly_fields = ("cost_input", "cost_output", "total_cost")

    def cost_input(self, obj):
        if not obj:
            return 0
        return obj.get_request_price().get("cost_input", 0)

    def cost_output(self, obj):
        if not obj:
            return 0
        return obj.get_request_price().get("cost_output", 0)

    def total_cost(self, obj):
        if not obj:
            return 0
        return obj.get_request_price().get("total_cost", 0)

    cost_input.short_description = "Cost input"
    cost_output.short_description = "Cost output"
    total_cost.short_description = "Total cost"


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
