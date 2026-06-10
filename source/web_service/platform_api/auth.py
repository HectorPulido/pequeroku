"""API-key authentication for the public ``/api/v1`` surface.

This is the ONLY authentication class on the v1 views (no session cookie), so the
surface is usable from scripts and agents and never relies on the IDE's login.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import APIKey

# Only refresh last_used_at at most this often, to avoid a DB write per request.
_LAST_USED_THROTTLE = timedelta(seconds=60)


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate ``Authorization: Bearer pk_<prefix>_<secret>``.

    Returns ``(user, api_key)`` so ``request.user`` is the key's owner and
    ``request.auth`` is the :class:`APIKey` (used for scope checks + throttling).
    Returns ``None`` (not an error) when there is no bearer token, letting DRF's
    ``IsAuthenticated`` produce a clean 401.
    """

    keyword = b"bearer"

    def authenticate(self, request):
        parts = authentication.get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed Authorization header")

        raw = parts[1].decode("latin-1")
        if not raw.startswith("pk_"):
            # A bearer token that isn't ours: treat as unauthenticated rather than
            # erroring, so a misrouted IDE token just yields 401.
            return None

        prefix, _, secret = raw[3:].partition("_")
        if not prefix or not secret:
            raise exceptions.AuthenticationFailed("Malformed API key")

        try:
            key = APIKey.objects.select_related("user").get(
                prefix=prefix, revoked=False
            )
        except APIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid API key")

        if not key.verify_secret(secret):
            raise exceptions.AuthenticationFailed("Invalid API key")

        if not key.user.is_active:
            raise exceptions.AuthenticationFailed("User is inactive")

        self._touch(key)
        return (key.user, key)

    def authenticate_header(self, request):
        return "Bearer"

    @staticmethod
    def _touch(key: APIKey) -> None:
        now = timezone.now()
        if key.last_used_at is None or (now - key.last_used_at) > _LAST_USED_THROTTLE:
            key.last_used_at = now
            key.save(update_fields=["last_used_at"])
