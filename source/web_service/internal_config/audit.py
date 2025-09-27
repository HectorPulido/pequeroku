from typing_extensions import cast
from django.utils import timezone
from django.http import HttpRequest
from asgiref.sync import sync_to_async

from django.contrib.auth.models import AnonymousUser

from .models import AuditLog


def _get_ip_from_request(request: HttpRequest | None) -> str | None:
    if not request:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_ua_from_request(request: HttpRequest | None) -> str:
    if not request:
        return ""
    return cast(str, request.META.get("HTTP_USER_AGENT", ""))


def audit_agent_tool(
    *,
    action: str,
    target_type: str = "",
    target_id: str = "",
    message: str = "",
    metadata: dict[str, object] | None = None,
    success: bool = True,
) -> None:
    """
    Register audit for HTTP/DRF
    """

    _ = AuditLog.objects.create(
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        message=message,
        metadata=metadata or {},
        success=success,
        created_at=timezone.now(),
    )


def audit_log_http(
    request: HttpRequest | None,
    *,
    action: str,
    target_type: str = "",
    target_id: str = "",
    message: str = "",
    metadata: dict[str, object] | None = None,
    success: bool = True,
) -> None:
    """
    Register audit for HTTP/DRF
    """

    user = getattr(request, "user", None) if request else None

    if isinstance(user, AnonymousUser):
        user = None

    _ = AuditLog.objects.create(
        user=user,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        message=message,
        metadata=metadata or {},
        ip=_get_ip_from_request(request),
        user_agent=_get_ua_from_request(request),
        success=success,
        created_at=timezone.now(),
    )


@sync_to_async
def audit_log_ws(
    *,
    action: str,
    user: object | None = None,  # channels scope user
    ip: str = "",
    user_agent: str = "",
    target_type: str = "",
    target_id: str = "",
    message: str = "",
    metadata: dict[str, object] | None = None,
    success: bool = True,
):
    _ = AuditLog.objects.create(
        user=user,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        message=message,
        metadata=metadata or {},
        ip=ip or None,
        user_agent=user_agent or "",
        success=success,
        created_at=timezone.now(),
    )
