from django.contrib import admin
from django.db import models
from django.forms import Textarea
from .models import (
    Container,
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
    AuditLog,
    AIUsageLog,
)


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("user", "container_id", "status", "created_at")


@admin.register(ResourceQuota)
class ResourceQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "max_containers", "max_memory_mb", "max_cpu_percent")


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "query", "created_at")


class FileTemplateItemInline(admin.TabularInline):
    model = FileTemplateItem
    extra = 1
    fields = ("order", "path", "mode", "content")
    formfield_overrides = {
        models.TextField: {
            "widget": Textarea(attrs={"rows": 18, "style": "font-family: monospace;"})
        }
    }


@admin.register(FileTemplate)
class FileTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "items_count", "updated_at", "created_at")
    search_fields = ("name", "slug", "description", "items__path")
    inlines = [FileTemplateItemInline]


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
