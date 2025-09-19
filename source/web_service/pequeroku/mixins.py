# vm_manager/mixins.py
from __future__ import annotations
import json
from typing import Optional, Tuple

from asgiref.sync import sync_to_async
from django.apps import apps


class WSBaseUtilsMixin:
    """
    WebSocket helpers: client IP, user-agent, and a consistent JSON sender.
    """

    def _ws_client_ip(self, scope) -> str:
        try:
            return scope.get("client", [None])[0] or ""
        except Exception:
            return ""

    def _ws_user_agent(self, scope) -> str:
        try:
            for k, v in scope.get("headers", []):
                if k == b"user-agent":
                    return v.decode("utf-8", "ignore")
        except Exception:
            pass
        return ""

    async def send_json_safe(self, obj: dict):
        """
        Explicit JSON writer that does not force ASCII. Useful when you need
        raw control over serialization (e.g. Console).
        """
        await self.send(text_data=json.dumps(obj, ensure_ascii=False))


class ContainerAccessMixin:
    """
    Shared helpers to validate ownership and fetch containers (optionally with node).
    """

    @staticmethod
    @sync_to_async
    def _user_owns_container(pk: int, user_pk: int) -> bool:
        User = apps.get_model("auth", "User")
        user = User.objects.get(pk=user_pk)
        if user.is_superuser:
            return True
        Container = apps.get_model("vm_manager", "Container")
        return Container.objects.filter(pk=pk, user_id=user_pk).exists()

    @staticmethod
    @sync_to_async
    def _get_container_simple(pk: int):
        """
        Returns Container or None.
        Matches AIConsumer's previous behavior.
        """
        Container = apps.get_model("vm_manager", "Container")
        try:
            return Container.objects.get(pk=pk)
        except Container.DoesNotExist:
            return None

    @staticmethod
    @sync_to_async
    def _get_container_with_node(
        pk: int, use_select_related: bool = False
    ) -> Tuple[Optional[object], Optional[object]]:
        """
        Returns (Container, Node) or (None, None).
        Matches Console/Editor behavior; Editor used select_related("node").
        """
        Container = apps.get_model("vm_manager", "Container")
        try:
            qs = Container.objects
            if use_select_related:
                qs = qs.select_related("node")
            obj = qs.get(pk=pk)
            return obj, getattr(obj, "node", None)
        except Container.DoesNotExist:
            return None, None


class AuditMixin(WSBaseUtilsMixin):
    """
    Small wrapper to call the existing audit function with repeated fields.
    """

    async def audit_ws(
        self,
        *,
        action: str,
        user,
        target_type: str,
        target_id: str,
        message: str,
        success: bool,
        metadata: Optional[dict] = None,
    ):
        from internal_config.audit import audit_log_ws  # local import to avoid cycles

        await audit_log_ws(
            action=action,
            user=user,
            ip=self._ws_client_ip(self.scope),
            user_agent=self._ws_user_agent(self.scope),
            target_type=target_type,
            target_id=target_id,
            message=message,
            metadata=metadata or {},
            success=success,
        )
