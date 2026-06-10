"""Session-authed account endpoints for the dashboard SPA.

These power the in-app "API & MCP" view: the logged-in user manages their own
keys (via the Django session set at login, same as the rest of `/api`) and reads
the MCP/API connection details. The public `/api/v1` surface uses API keys; this
one rides the session, so the SPA can call it with no key.
"""

from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import APIKey


def _serialize(key: APIKey) -> dict:
    return {
        "id": key.pk,
        "name": key.name,
        "prefix": key.prefix,
        "scopes": key.scopes,
        "last_used_at": key.last_used_at,
        "revoked": key.revoked,
        "created_at": key.created_at,
    }


class AccountAPIKeyViewSet(viewsets.ViewSet):
    """`/api/account/api-keys/` — list / create / revoke the caller's API keys."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        keys = APIKey.objects.filter(user=request.user).order_by("-created_at")
        return Response([_serialize(k) for k in keys])

    def create(self, request):
        name = (request.data.get("name") or "").strip() or "api-key"
        raw_scopes = request.data.get("scopes", None)
        if raw_scopes is None:
            # Omitted → sensible default. Explicit-but-empty/invalid → error below.
            scopes = [APIKey.SCOPE_READ, APIKey.SCOPE_EXEC]
        else:
            scopes = [s for s in raw_scopes if s in APIKey.SCOPE_CHOICES]
            if not scopes:
                return Response({"detail": "Pick at least one scope."}, status=400)

        obj, token = APIKey.create_key(user=request.user, name=name, scopes=scopes)
        data = _serialize(obj)
        # The full secret is returned exactly once, here.
        data["token"] = token
        return Response(data, status=201)

    def destroy(self, request, pk=None):
        updated = APIKey.objects.filter(pk=pk, user=request.user).update(revoked=True)
        if not updated:
            return Response({"detail": "Not found"}, status=404)
        return Response(status=204)

    @action(detail=False, methods=["get"], url_path="mcp-info")
    def mcp_info(self, request):
        base = f"{request.scheme}://{request.get_host()}"
        return Response(
            {
                "mcp_url": f"{base}/mcp",
                "api_base": f"{base}/api/v1",
                "swagger_url": f"{base}/api/v1/schema/swagger-ui/",
            }
        )
