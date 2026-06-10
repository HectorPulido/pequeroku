"""Stable error contract for ``/api/v1``: ``{"error": {"code", "message"}}``.

Every v1 view returns this envelope with an enumerated ``code`` instead of DRF's
default ad-hoc bodies, so clients (SDK, MCP) can branch on a stable string. The
handler is wired ONLY on the v1 views (via ``get_exception_handler``), leaving the
IDE's ``/api`` error shapes untouched.
"""

from __future__ import annotations

from rest_framework import status as drf_status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

# Enumerated error codes → default HTTP status.
ERROR_STATUS = {
    "invalid_request": drf_status.HTTP_400_BAD_REQUEST,
    "unauthorized": drf_status.HTTP_401_UNAUTHORIZED,
    "forbidden_scope": drf_status.HTTP_403_FORBIDDEN,
    "quota_exceeded": drf_status.HTTP_403_FORBIDDEN,
    "type_not_allowed": drf_status.HTTP_403_FORBIDDEN,
    "not_found": drf_status.HTTP_404_NOT_FOUND,
    "method_not_allowed": drf_status.HTTP_405_METHOD_NOT_ALLOWED,
    "conflict": drf_status.HTTP_409_CONFLICT,
    "machine_not_running": drf_status.HTTP_409_CONFLICT,
    "rate_limited": drf_status.HTTP_429_TOO_MANY_REQUESTS,
    "node_unavailable": drf_status.HTTP_503_SERVICE_UNAVAILABLE,
    "upstream_error": drf_status.HTTP_502_BAD_GATEWAY,
    "timeout": drf_status.HTTP_504_GATEWAY_TIMEOUT,
    "internal_error": drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
}

# DRF builtin status → our code, for exceptions we don't raise ourselves.
_STATUS_TO_CODE = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden_scope",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
    503: "node_unavailable",
}


class APIError(APIException):
    """Raise to emit ``{"error": {"code", "message"}}`` with a chosen code."""

    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code or ERROR_STATUS.get(code, 400)
        super().__init__(detail=message)


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def platform_exception_handler(exc, context):
    """DRF exception handler that normalizes everything into the envelope."""
    if isinstance(exc, APIError):
        return Response(_envelope(exc.code, exc.message), status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled (e.g. a bug): don't leak a stack trace to API clients.
        return Response(
            _envelope("internal_error", "Internal server error"),
            status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _STATUS_TO_CODE.get(response.status_code, "invalid_request")
    message = _extract_message(response.data)
    response.data = _envelope(code, message)
    return response


def _extract_message(data) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        # Field validation errors: surface the first one compactly.
        for field, errs in data.items():
            if isinstance(errs, (list, tuple)) and errs:
                return f"{field}: {errs[0]}"
            return f"{field}: {errs}"
        return "Request failed"
    if isinstance(data, (list, tuple)) and data:
        return str(data[0])
    return str(data)
