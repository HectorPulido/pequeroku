"""Scope-based permission for the v1 surface.

Each view declares the scope an action needs via ``view.required_scope()``; this
permission checks the authenticated key grants it. Failures raise the v1 error
envelope (``forbidden_scope``) rather than DRF's default body.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from .errors import APIError


class HasRequiredScope(BasePermission):
    def has_permission(self, request, view) -> bool:
        api_key = getattr(request, "auth", None)
        if api_key is None or not hasattr(api_key, "has_scope"):
            return False

        required = None
        getter = getattr(view, "required_scope", None)
        if callable(getter):
            required = getter()
        if not required:
            return True

        if not api_key.has_scope(required):
            raise APIError(
                "forbidden_scope",
                f"This API key lacks the '{required}' scope required for this action.",
            )
        return True
