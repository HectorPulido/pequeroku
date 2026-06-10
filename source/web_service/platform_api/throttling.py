"""Per-API-key rate limiting for the v1 surface.

Keyed on the authenticated key id, so each key gets its own budget regardless of
the IP it calls from. Rate is configurable via ``PLATFORM_API_THROTTLE_RATE``.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class APIKeyRateThrottle(SimpleRateThrottle):
    scope = "platform_api_key"
    # Set directly so SimpleRateThrottle doesn't require a DEFAULT_THROTTLE_RATES
    # entry; still overridable via settings for ops tuning.
    rate = getattr(settings, "PLATFORM_API_THROTTLE_RATE", "120/min")

    def get_cache_key(self, request, view):
        api_key = getattr(request, "auth", None)
        if api_key is None or not getattr(api_key, "pk", None):
            return None  # unauthenticated requests aren't throttled here (they 401)
        return f"throttle_platform_apikey_{api_key.pk}"
