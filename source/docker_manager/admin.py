# File: docker_manager/admin.py

from django.contrib import admin
from .models import Container, ResourceQuota


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("user", "container_id", "status", "created_at")


@admin.register(ResourceQuota)
class ResourceQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "max_containers", "max_memory_mb", "max_cpu_percent")
