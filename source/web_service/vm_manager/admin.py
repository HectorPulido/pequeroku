from django.contrib import admin
from django.db import models
from django.utils.html import format_html, format_html_join
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
    readonly_fields = ("extra_details",)

    @admin.display(description="Resources")
    def extra_details(self, obj):
        if not obj:
            return "-"

        node_score = obj.get_node_score()
        running_containers = obj.get_running_containers()
        free_vcpus, free_vram = obj.get_free_resources()
        used_vcpus, used_vram = obj.get_used_resources()

        rows = [
            ("Running containers", running_containers),
            ("Node score", node_score),
            ("Used vCPUs", f"{used_vcpus} / {obj.capacity_vcpus}"),
            ("Used VRAM", f"{used_vram}mb / {obj.capacity_mem_mb}mb"),
            ("Free vCPUs", f"{free_vcpus}"),
            ("Free VRAM", f"{free_vram} mb"),
        ]
        return format_html(
            '<table style="width:auto" class="adminlist">{}</table>',
            format_html_join(
                "",
                "<tr><th style='text-align:left;padding-right:12px'>{}</th><td>{}</td></tr>",
                ((label, value) for label, value in rows),
            ),
        )


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("name", "node", "user", "status", "created_at")
    readonly_fields = (
        "ai_logs",
        "extra_details",
    )

    @admin.display(description="AI Logs")
    def ai_logs(self, obj):
        if not obj:
            return "-"

        logs = []
        logs = obj.get_user_ai_logs()

        logs.insert(
            0,
            (
                "query",
                "response",
                "created_at",
            ),
        )
        return format_html(
            '<table style="width:auto" class="adminlist">{}</table>',
            format_html_join(
                "",
                "<tr><th>{}</th><td>{}</td><td>{}</td></tr>",
                ((query, response, created_at) for query, response, created_at in logs),
            ),
        )

    @admin.display(description="Logs")
    def extra_details(self, obj):
        if not obj:
            return "-"

        logs = obj.get_machine_logs()
        logs.insert(
            0,
            (
                "action",
                "message",
                "metadata",
                "success",
                "created_at",
            ),
        )
        return format_html(
            '<table style="width:auto" class="adminlist">{}</table>',
            format_html_join(
                "",
                "<tr><th>{}</th><th>{}</th><td>{}</td><td>{}</td><td>{}</td></tr>",
                (
                    (action, message, metadata, success, created_at)
                    for action, message, metadata, success, created_at in logs
                ),
            ),
        )


class ContainersInline(admin.TabularInline):
    model = Container
    extra = 1
    fields = (
        "node",
        "name",
        "memory_mb",
        "vcpus",
        "disk_gib",
        "desired_state",
        "status",
    )
    formfield_overrides = {
        models.TextField: {
            "widget": Textarea(attrs={"rows": 18, "style": "font-family: monospace;"})
        }
    }


@admin.register(ResourceQuota)
class ResourceQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "max_containers", "max_memory_mb", "vcpus")
    readonly_fields = ("logs", "ai_logs")
    inlines = [ContainersInline]

    @admin.display(description="Logs")
    def logs(self, obj):
        if not obj:
            return "-"

        logs = []
        try:
            logs = obj.get_user_logs()
        except Exception as e:
            print(e)

        logs.insert(
            0,
            (
                "action",
                "message",
                "metadata",
                "success",
                "created_at",
            ),
        )
        return format_html(
            '<table style="width:auto" class="adminlist">{}</table>',
            format_html_join(
                "",
                "<tr><th>{}</th>,<th>{}</th><td>{}</td><td>{}</td><td>{}</td></tr>",
                (
                    (action, message, metadata, success, created_at)
                    for action, message, metadata, success, created_at in logs
                ),
            ),
        )

    @admin.display(description="AI Logs")
    def ai_logs(self, obj):
        if not obj:
            return "-"

        logs = []
        logs = obj.get_user_ai_logs()

        logs.insert(
            0,
            (
                "query",
                "response",
                "container",
                "created_at",
            ),
        )
        return format_html(
            '<table style="width:auto" class="adminlist">{}</table>',
            format_html_join(
                "",
                "<tr><th>{}</th><td>{}</td><td>{}</td><td>{}</td></tr>",
                (
                    (query, response, container, created_at)
                    for query, response, container, created_at in logs
                ),
            ),
        )


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
