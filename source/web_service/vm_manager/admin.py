from django.contrib import admin
from django.db import models
from django.forms import Textarea
from .models import (
    Container,
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
    Node,
)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ("name", "node_host", "active")


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("name", "node", "user", "status", "created_at")


@admin.register(ResourceQuota)
class ResourceQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "max_containers", "max_memory_mb", "vcpus")


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
    list_display = ("name", "items_count", "updated_at", "public", "created_at")
    search_fields = ("name", "slug", "description", "items__path")
    inlines = [FileTemplateItemInline]
