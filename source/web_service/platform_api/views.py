"""Public v1 ViewSets: containers + types.

These reuse ``vm_manager.orchestration`` (creation/scheduling/quota) and
``platform_api.vmops`` (node ops), so the public surface is a thin contract layer
over the same substrate the IDE uses — no privileged side paths.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from vm_manager import orchestration
from vm_manager.models import Container, ContainerType

from . import idempotency, vmops
from .auth import APIKeyAuthentication
from .errors import APIError, platform_exception_handler
from .models import APIKey
from .pagination import V1Pagination
from .permissions import HasRequiredScope
from .serializers import (
    ContainerActionSerializer,
    ContainerCreateSerializer,
    ContainerSerializer,
    ContainerTypeSerializer,
    ExecSerializer,
    FilesUploadSerializer,
    ProcessCreateSerializer,
)
from .throttling import APIKeyRateThrottle


class PlatformViewSet(viewsets.ViewSet):
    """Base for v1 viewsets: API-key auth, scope perms, throttle, error envelope."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, HasRequiredScope]
    throttle_classes = [APIKeyRateThrottle]

    def get_exception_handler(self):
        # Scope the v1 envelope to these views only; the IDE's /api keeps DRF's.
        return platform_exception_handler

    def required_scope(self) -> str:
        return APIKey.SCOPE_READ


class ContainerViewSet(PlatformViewSet):
    """``/api/v1/containers`` — create, inspect, drive and destroy containers."""

    def required_scope(self) -> str:
        act = self.action
        method = self.request.method
        if act in ("create", "destroy"):
            return APIKey.SCOPE_ADMIN
        if act == "files":
            return APIKey.SCOPE_EXEC if method in ("PUT", "POST") else APIKey.SCOPE_READ
        if act == "process":
            return APIKey.SCOPE_EXEC if method == "DELETE" else APIKey.SCOPE_READ
        if act in ("exec_cmd", "processes", "actions"):
            return APIKey.SCOPE_EXEC
        return APIKey.SCOPE_READ

    # --- helpers ---------------------------------------------------------

    def _owned(self):
        return (
            Container.objects.filter(user=self.request.user)
            .exclude(is_pool=True)
            .select_related("node", "container_type")
        )

    def _get(self, pk) -> Container:
        try:
            return self._owned().get(pk=pk)
        except (Container.DoesNotExist, ValueError, TypeError):
            raise APIError("not_found", "Container not found")

    def _resolve_type(self, quota, value) -> ContainerType:
        # Numeric → exact pk.
        try:
            return ContainerType.objects.get(pk=int(value))
        except (ValueError, TypeError, ContainerType.DoesNotExist):
            pass
        # By name: prefer one the user is allowed to use, since names can collide
        # with seeded/other types. Fall back to a global match (the allowed/credit
        # checks downstream still gate it).
        ct = quota.allowed_types.filter(container_type_name=str(value)).first()
        if ct is None:
            ct = ContainerType.objects.filter(container_type_name=str(value)).first()
        if ct is None:
            raise APIError("invalid_request", f"Unknown container type '{value}'")
        return ct

    # --- collection ------------------------------------------------------

    def list(self, request):
        qs = self._owned().order_by("-created_at")
        paginator = V1Pagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = ContainerSerializer(page, many=True).data
        return paginator.get_paginated_response(data)

    def create(self, request):
        cache_key, cached = idempotency.lookup(request, "containers")
        if cached is not None:
            return Response(cached["data"], status=cached["status"])

        ser = ContainerCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data_in = ser.validated_data

        quota = orchestration.check_quota(request.user)
        if quota is None:
            raise APIError("quota_exceeded", "No active quota assigned to this user")

        ct = self._resolve_type(quota, data_in["type"])
        if not quota.allowed_types.filter(pk=ct.pk).exists():
            raise APIError(
                "type_not_allowed", "This container type is not allowed for your quota"
            )
        if not quota.can_create_container(container_type=ct):
            raise APIError(
                "quota_exceeded",
                "Not enough credits for this type; destroy a container or pick a "
                "cheaper type.",
            )

        ttl = data_in.get("ttl_seconds")
        expires_at = timezone.now() + timedelta(seconds=ttl) if ttl else None
        name = data_in.get("name") or None

        try:
            container, warning, _from_pool = orchestration.claim_or_create_container(
                user=request.user, ct=ct, name=name, expires_at=expires_at
            )
        except orchestration.NoNodeAvailable:
            raise APIError(
                "node_unavailable", "No node available to place the container"
            )

        out = ContainerSerializer(container).data
        if warning:
            out["warning"] = warning
        idempotency.store(cache_key, status.HTTP_201_CREATED, out)
        return Response(out, status=status.HTTP_201_CREATED)

    # --- item ------------------------------------------------------------

    def retrieve(self, request, pk=None):
        c = self._get(pk)
        try:
            resp = orchestration.get_service(c).get_vm(str(c.container_id))
            new_state = resp.get("state")
            if new_state and new_state != c.status:
                c.status = new_state
                c.save(update_fields=["status"])
        except Exception:
            pass
        return Response(ContainerSerializer(c).data)

    def destroy(self, request, pk=None):
        c = self._get(pk)
        vmops.destroy(c)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --- actions ---------------------------------------------------------

    @action(detail=True, methods=["post"])
    def actions(self, request, pk=None):
        c = self._get(pk)
        ser = ContainerActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        name = ser.validated_data["action"]
        vmops.action(c, name)
        if name in ("start", "restart"):
            c.desired_state = Container.DesirableStatus.RUNNING
        elif name == "stop":
            c.desired_state = Container.DesirableStatus.STOPPED
        c.save(update_fields=["desired_state"])
        return Response({"status": "ok", "action": name})

    @action(detail=True, methods=["post"], url_path="exec")
    def exec_cmd(self, request, pk=None):
        c = self._get(pk)
        ser = ExecSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        command = ser.validated_data["command"]
        if ser.validated_data.get("background"):
            return Response(vmops.start_process(c, command))
        result = vmops.exec_sh(c, command, timeout=ser.validated_data.get("timeout"))
        return Response(result)

    @action(detail=True, methods=["post"])
    def processes(self, request, pk=None):
        c = self._get(pk)
        ser = ProcessCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(vmops.start_process(c, ser.validated_data["command"]))

    @action(
        detail=True,
        methods=["get", "delete"],
        url_path=r"processes/(?P<pid>[^/]+)",
    )
    def process(self, request, pk=None, pid=None):
        c = self._get(pk)
        if request.method == "DELETE":
            return Response(vmops.stop_process(c, pid))
        return Response(vmops.process_status(c, pid))

    @action(detail=True, methods=["get", "put"])
    def files(self, request, pk=None):
        c = self._get(pk)
        if request.method == "PUT":
            ser = FilesUploadSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            return Response(
                vmops.upload_files(
                    c,
                    ser.validated_data["files"],
                    dest_path=ser.validated_data.get("dest_path", "/"),
                    clean=ser.validated_data.get("clean", False),
                )
            )
        path = request.query_params.get("path")
        if not path:
            raise APIError("invalid_request", "Query param 'path' is required")
        return Response(vmops.read_file(c, path))

    @action(detail=True, methods=["get"])
    def dirs(self, request, pk=None):
        c = self._get(pk)
        path = request.query_params.get("path", "/app")
        return Response(vmops.list_dir(c, path))

    @action(detail=True, methods=["get"])
    def ports(self, request, pk=None):
        c = self._get(pk)
        ports = vmops.listening_ports(c)
        for p in ports:
            # Informative only; access still requires auth (token/session).
            p["preview_path"] = f"/api/containers/{c.pk}/preview/{p.get('port')}/"
        return Response(ports)


class ContainerTypeViewSet(PlatformViewSet):
    """``/api/v1/types`` — flavors available to the key owner + credit cost."""

    def list(self, request):
        quota = orchestration.check_quota(request.user)
        if quota and quota.allowed_types.exists():
            qs = quota.allowed_types.all()
        else:
            qs = ContainerType.objects.none()
        return Response(ContainerTypeSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        quota = orchestration.check_quota(request.user)
        allowed = quota.allowed_types.all() if quota else ContainerType.objects.none()
        ct = allowed.filter(pk=pk).first()
        if ct is None:
            raise APIError("not_found", "Type not found")
        return Response(ContainerTypeSerializer(ct).data)
