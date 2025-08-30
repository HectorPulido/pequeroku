from django.contrib import admin
from .models import Config


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    """
    Admin configuration for the Config model.
    """

    list_display = ("id", "name", "value", "description")
