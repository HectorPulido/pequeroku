from django.contrib import admin

from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("prefix", "name", "user", "scopes", "revoked", "last_used_at")
    list_filter = ("revoked",)
    search_fields = ("prefix", "name", "user__username")
    # The secret is never stored, so there's nothing sensitive to hide beyond the
    # hash; keep it read-only to avoid accidental edits that would brick the key.
    readonly_fields = ("prefix", "hashed_key", "last_used_at", "created_at")
