import os
import base64
import logging
from dataclasses import asdict
from typing import cast

import requests

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema

from internal_config.audit import audit_log_http

from .preview_proxy import build_preview_response
from .serializers import (
    ContainerSerializer,
    UserInfoSerializer,
    FileTemplateSerializer,
    ApplyTemplateRequestSerializer,
    ApplyTemplateResponseSerializer,
    ContainerTypeSerializer,
)
from .models import Container, FileTemplate, ContainerType
from .vm_client import VMAction, VMUploadFiles, VMFile

from .templates import (
    apply_template,
)

from . import orchestration

from .mixin import VMSyncMixin

from ai_services import conversations as convo

logger = logging.getLogger(__name__)


class ContainersViewSet(viewsets.ModelViewSet, VMSyncMixin):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerSerializer
    queryset = Container.objects.all()

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return Container.objects.none()

        # Warm-pool VMs are infrastructure (owned by the __pool__ system user) and
        # are managed by the prewarm command, not the user-facing API. Hide them
        # from every API view, including superusers; once claimed (is_pool=False)
        # they show up normally. Operators can still inspect them in the admin.
        if user.is_superuser:
            return (
                super()
                .get_queryset()
                .exclude(is_pool=True)
                .select_related("node")
                .prefetch_related("allowed_users")
            )

        return (
            Container.visible_containers_for(user)
            .exclude(is_pool=True)
            .prefetch_related("allowed_users")
        )

    def _require_owner(self, request, obj):
        """Return a 403 Response if the requester is not the owner (nor a
        superuser), else ``None``. Guards owner-only actions — rename, delete
        and managing collaborators — that ``get_queryset()`` would otherwise
        expose to collaborators (who can *see* the container but not own it)."""
        if obj.user_id != request.user.id and not request.user.is_superuser:
            return Response(
                {"error": "Only the owner can perform this action"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _owner_quota(self, obj):
        """Quota that gates in-place actions (power/upload/download/...).

        Credits always accrue to the container's owner and collaborators keep
        100% of their own credits, so these actions are gated by the *owner's*
        quota, never the requester's. ``duplicate`` is the exception (it mints a
        new container owned by the requester) and keeps ``_check_quota``.
        """
        return orchestration.check_quota(obj.user)

    def list(self, request, *args, **kwargs):
        """
        List and sync the nodes
        """
        queryset = self.filter_queryset(self.get_queryset().select_related("node"))

        page = self.paginate_queryset(queryset)
        objs = list(page) if page is not None else list(queryset)

        if objs:
            changed = self._sync_statuses(objs)
            if changed:
                type(objs[0]).objects.bulk_update(changed, ["status"], batch_size=200)

        serializer = self.get_serializer(objs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        service = self._get_service(obj)
        response = service.get_vm(str(obj.container_id))

        obj.status = response.get("state", "error")
        obj.save()

        serializer = self.get_serializer(obj)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        quota = self._check_quota(request)
        if not quota:
            audit_log_http(
                request,
                action="container.create",
                message="Create attempt without assigned quota",
                success=False,
            )
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        # Resolve requested container type (if any)
        ct_id = cast(str | None, request.data.get("container_type"))
        ct_name = cast(str | None, request.data.get("container_name"))

        if not ct_id:
            audit_log_http(
                request,
                action="container.create",
                message="Invalid container type",
                metadata={"container_type": ct_id},
                success=False,
            )
            return Response(
                "Invalid container type", status=status.HTTP_400_BAD_REQUEST
            )

        ct: ContainerType | None = None
        try:
            ct = ContainerType.objects.get(pk=int(ct_id))
        except:
            audit_log_http(
                request,
                action="container.create",
                message="Invalid container type",
                metadata={"container_type": ct_id},
                success=False,
            )
            return Response(
                "Invalid container type", status=status.HTTP_400_BAD_REQUEST
            )

        # This will not happen
        if not ct or not isinstance(ct, ContainerType):
            audit_log_http(
                request,
                action="container.create",
                message="Invalid container type",
                metadata={"container_type": ct_id},
                success=False,
            )
            return Response(
                "Invalid container type", status=status.HTTP_400_BAD_REQUEST
            )

        if not quota.allowed_types.filter(pk=ct.pk).exists():
            audit_log_http(
                request,
                action="container.create",
                message="Container type not allowed for this quota",
                metadata={"container_type": ct.pk},
                success=False,
            )
            return Response(
                "Container type not allowed for this quota",
                status=status.HTTP_403_FORBIDDEN,
            )

        can_create = quota.can_create_container(container_type=ct)
        if not can_create:
            audit_log_http(
                request,
                action="container.create",
                message="Not enough credits for selected type",
                metadata={
                    "container_type": cast(int, ct.pk),
                    "credits_cost": getattr(ct, "credits_cost", None),
                },
                success=False,
            )
            return Response(
                "Not enough credits for selected type",
                status=status.HTTP_403_FORBIDDEN,
            )

        # Claim a warm-pool VM if one is ready, else boot on demand. The shared
        # orchestration helper is also what powers the public /api/v1 surface, so
        # both paths stay in sync.
        try:
            c, warn_msg, from_pool = orchestration.claim_or_create_container(
                user=request.user, ct=ct, name=ct_name
            )
        except orchestration.NoNodeAvailable:
            return Response(
                "No node available",
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        if from_pool:
            audit_log_http(
                request,
                action="container.create",
                target_type="container",
                target_id=c.pk,
                message="Container claimed from warm pool",
                metadata={
                    "container_id": str(c.container_id),
                    "container_type": str(ct.pk),
                    "credits_cost": getattr(ct, "credits_cost", None),
                    "pool": True,
                },
                success=True,
            )
        else:
            audit_log_http(
                request,
                action="container.create",
                target_type="container",
                target_id=c.pk,
                message="Container record created and VM boot scheduled",
                metadata={
                    "container_id": str(c.container_id),
                    "container_type": str(ct.pk),
                    "credits_cost": getattr(ct, "credits_cost", None),
                },
                success=True,
            )

        ser = self.get_serializer(c)
        data = dict(ser.data)
        if warn_msg:
            data["warning"] = warn_msg
        resp = Response(data, status=status.HTTP_201_CREATED)
        if warn_msg:
            resp["X-Warning"] = warn_msg
        return resp

    @action(detail=True, methods=["patch"])
    def rename(self, request, pk=None):
        """PATCH /api/containers/{pk}/rename/ — change the friendly name.

        The name is a Django-side label only (the VM is identified by its
        ``container_id``), so this is a pure metadata update and never touches
        the vm-service. Renaming is owner-only — collaborators can see and use
        the container but not relabel it.
        """
        obj: Container = self.get_object()
        denied = self._require_owner(request, obj)
        if denied:
            return denied

        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        raw_name = request.data.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            return Response(
                {"error": "name required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if len(name) > 128:
            return Response(
                {"error": "name too long (max 128 characters)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj.name = name
        obj.save(update_fields=["name"])

        audit_log_http(
            request,
            action="container.rename",
            target_type="container",
            target_id=obj.pk,
            message="Container renamed",
            metadata={"name": name},
            success=True,
        )

        serializer = self.get_serializer(obj)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "put"])
    def allowed_users(self, request, pk=None):
        """GET/PUT /api/containers/{pk}/allowed_users/ — manage collaborators.

        Collaborators can use the VM (IDE, terminal, AI, power, duplicate,
        files) but cannot rename it, delete it, or edit this list. Reading and
        writing the list is owner-only.

        PUT body: ``{"usernames": ["alice", "bob"]}`` replaces the whole list.
        Unknown usernames are ignored and echoed back under ``not_found`` so the
        UI can flag typos; the owner is never added to their own list.
        """
        obj: Container = self.get_object()
        denied = self._require_owner(request, obj)
        if denied:
            return denied

        if request.method == "GET":
            return Response(
                {"usernames": sorted(u.username for u in obj.allowed_users.all())}
            )

        raw = request.data.get("usernames", [])
        if not isinstance(raw, list):
            return Response(
                {"error": "usernames must be a list of strings"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Normalize: trim, drop blanks/dupes; ignore the owner (can't self-share).
        requested: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if not name or name in seen or name == obj.user.username:
                continue
            seen.add(name)
            requested.append(name)

        if len(requested) > 50:
            return Response(
                {"error": "too many collaborators (max 50)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        found = list(
            User.objects.filter(username__in=requested).exclude(pk=obj.user_id)
        )
        found_names = {u.username for u in found}
        not_found = [n for n in requested if n not in found_names]

        obj.allowed_users.set(found)

        audit_log_http(
            request,
            action="container.allowed_users.set",
            target_type="container",
            target_id=obj.pk,
            message="Updated collaborator access list",
            metadata={"usernames": sorted(found_names), "not_found": not_found},
            success=True,
        )

        return Response({"usernames": sorted(found_names), "not_found": not_found})

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """POST /api/containers/{pk}/duplicate/ — clone a stopped container.

        Disk-level duplicate: the vm-service copies the source VM's qcow2 overlay
        into a new VM on the SAME node, so the copy boots with identical data.
        Respects quota exactly like ``create`` and requires the source to be
        stopped (copying a live qcow2 would corrupt it).
        """
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        source: Container = self.get_object()

        ct = source.container_type
        if ct is None:
            return Response(
                {"error": "Container has no type; cannot duplicate"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A disk copy is only safe on a quiesced qcow2, so the source must be off.
        # The node is the hard gate (409); this gives a clearer, earlier message.
        if source.status == Container.Status.RUNNING:
            return Response(
                {"error": "Stop the container before duplicating"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not quota.allowed_types.filter(pk=ct.pk).exists():
            return Response(
                "Container type not allowed for this quota",
                status=status.HTTP_403_FORBIDDEN,
            )
        if not quota.can_create_container(container_type=ct):
            return Response(
                "Not enough credits for selected type",
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            c, warn_msg = orchestration.duplicate_container(
                user=request.user, source=source, name=f"{source.name}-copy"
            )
        except orchestration.NoNodeAvailable:
            return Response("No node available", status=status.HTTP_501_NOT_IMPLEMENTED)
        except requests.HTTPError as e:
            # The node refused (e.g. the source is still running, or has no disk
            # yet). Surface a clean 400 instead of a 500. No DB row was created.
            return Response(
                {"error": "Could not duplicate container", "detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        audit_log_http(
            request,
            action="container.duplicate",
            target_type="container",
            target_id=c.pk,
            message="Container duplicated from source",
            metadata={
                "source_id": source.pk,
                "source_container_id": source.container_id,
                "new_container_id": c.container_id,
            },
            success=True,
        )

        data = dict(self.get_serializer(c).data)
        if warn_msg:
            data["warning"] = warn_msg
        return Response(data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        denied = self._require_owner(request, obj)
        if denied:
            return denied

        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        service = self._get_service(obj)
        try:
            service.delete_vm(obj.container_id)
        except Exception as e:
            logger.warning("Could not stop vm, deleting anyway: %s", e)

        audit_log_http(
            request,
            action="container.destroy",
            target_type="container",
            target_id=obj.pk,
            message="Requested container deletion (attempting soft shutdown)",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        self.perform_destroy(obj)
        return Response({"status": "stopped"})

    @action(detail=True, methods=["post"])
    def exec_command(self, request, pk=None):
        cmd = request.data.get("cmd")
        if not cmd:
            return Response("No command", status=status.HTTP_400_BAD_REQUEST)
        obj: Container = self.get_object()
        service = self._get_service(obj)
        response = service.execute_sh(str(obj.container_id), cmd)

        audit_log_http(
            request,
            action="container.send_command",
            target_type="container",
            target_id=obj.pk,
            message=cmd,
            metadata={"response": response},
            success=False,
        )

        return Response(response)

    @action(detail=True, methods=["get"])
    def ports(self, request, pk=None):
        """GET /api/containers/{pk}/ports/ — TCP ports detected listening in the VM.

        Feeds the IDE preview port selector (autodetection). Read-only; container
        visibility is enforced by get_object()/get_queryset. Returns ``[]`` instead
        of erroring while the VM is still booting or the app isn't up yet, so the
        front can poll smoothly. Each item is ``{port, address, process?, pid?}``.
        """
        obj: Container = self.get_object()
        service = self._get_service(obj)
        try:
            response = service.listening_ports(str(obj.container_id))
        except Exception:
            response = []
        return Response(response)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        f = request.FILES.get("file")
        dest = request.data.get("dest_path", "/app")

        if not f:
            audit_log_http(
                request,
                action="container.upload_file",
                target_type="container",
                target_id=obj.pk,
                message="Upload rejected: no file provided",
                metadata={"dest_path": dest},
                success=False,
            )
            return Response({"error": "file required"}, status=400)
        service = self._get_service(obj)
        response = None
        try:
            raw = f.read()
            try:
                text = raw.decode("utf-8")
                file_payload = VMFile(path=f.name, text=text)
            except UnicodeDecodeError:
                b64 = base64.b64encode(raw).decode("ascii")
                file_payload = VMFile(path=f.name, content_b64=b64)

            payload = VMUploadFiles(dest_path=dest, clean=False, files=[file_payload])
            data = asdict(payload)
            response = service.upload_files_blob(str(obj.container_id), data)

        except Exception as e:
            return Response(
                {"error": "invalid file or encoding", "detail": str(e)}, status=400
            )

        if not response:
            return Response({"error": "invalid file or encoding"}, status=400)

        audit_log_http(
            request,
            action="container.upload_file",
            target_type="container",
            target_id=obj.pk,
            message="File uploaded via SFTP",
            metadata={"remote_path": dest, "length": response.get("length", 0)},
            success=True,
        )
        return Response(response)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        service = self._get_service(obj)
        # Rebuild the VM record on the node if its cache lost it (e.g. vm-service
        # restart); idempotent and avoids a 404 on start.
        self.ensure_vm_record(obj, service)
        service.action_vm(
            str(obj.container_id), action=VMAction(action="start", cleanup_disks=False)
        )

        obj.desired_state = Container.DesirableStatus.RUNNING
        obj.save(update_fields=["desired_state"])

        audit_log_http(
            request,
            action="container.power_on",
            target_type="container",
            target_id=obj.pk,
            message="Power on requested",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        return Response({"status": "starting...", "desired_state": obj.desired_state})

    @action(detail=True, methods=["post"])
    def power_off(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        service = self._get_service(obj)
        service.action_vm(
            str(obj.container_id), action=VMAction(action="stop", cleanup_disks=False)
        )

        obj.desired_state = Container.DesirableStatus.STOPPED
        obj.save(update_fields=["desired_state"])

        audit_log_http(
            request,
            action="container.power_off",
            target_type="container",
            target_id=obj.pk,
            message="Power off requested",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        return Response({"status": "stopping...", "desired_state": obj.desired_state})

    @action(detail=True, methods=["post"])
    def restart_container(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        service = self._get_service(obj)
        service.action_vm(
            str(obj.container_id), action=VMAction(action="reboot", cleanup_disks=False)
        )
        audit_log_http(
            request,
            action="container.restart_shell",
            target_type="container",
            target_id=obj.pk,
            message="Shell channel reopened",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        return Response({"status": "restarted"})

    @action(detail=True, methods=["get"])
    def download_file(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        path = request.query_params.get("path")
        if not path:
            return Response({"error": "path required"}, status=400)

        service = self._get_service(obj)
        r = service.download_file(str(obj.container_id), path)

        if r.status_code >= 400:
            try:
                return Response(r.json(), status=r.status_code)
            except Exception:
                return Response({"error": "download failed"}, status=r.status_code)

        filename = os.path.basename(path) or "download"
        content_type = r.headers.get("Content-Type", "application/octet-stream")
        content_disposition = r.headers.get(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )

        resp = HttpResponse(content=r.content, content_type=content_type)
        resp["Content-Disposition"] = content_disposition
        return resp

    @action(detail=True, methods=["get"])
    def download_folder(self, request, pk=None):
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        root = request.query_params.get("root", "/app")
        prefer_fmt = request.query_params.get("prefer_fmt", "zip")

        service = self._get_service(obj)
        r = service.download_folder(
            str(obj.container_id), root=root, prefer_fmt=prefer_fmt
        )

        if r.status_code >= 400:
            try:
                return Response(r.json(), status=r.status_code)
            except Exception:
                return Response({"error": "download failed"}, status=r.status_code)

        base = os.path.basename(root.rstrip("/")) or "archive"

        if prefer_fmt == "zip" and r.headers.get("Content-Disposition") is None:
            filename = f"{base}.zip"
        elif prefer_fmt == "tar.gz" and r.headers.get("Content-Disposition") is None:
            filename = f"{base}.tar.gz"
        else:
            filename = None

        content_type = r.headers.get("Content-Type", "application/octet-stream")
        content_disposition = r.headers.get(
            "Content-Disposition",
            f'attachment; filename="{filename}"' if filename else None,
        )

        resp = HttpResponse(content=r.content, content_type=content_type)
        if content_disposition:
            resp["Content-Disposition"] = content_disposition
        return resp

    # NB: registered explicitly in urls.py (NOT via the router) so the catch-all
    # path matches with or without a trailing slash — apps POST to arbitrary URLs
    # and the router's forced trailing slash would 404 → APPEND_SLASH RuntimeError.
    # Excluded from the OpenAPI schema: it's a wildcard binary proxy (media_type
    # ``*/*``, format ``None``) with no meaningful OpenAPI shape, and enumerating it
    # crashes drf_spectacular's renderer resolution on the ``None`` format.
    @extend_schema(exclude=True)
    @xframe_options_exempt
    def preview(self, request, pk=None, port=None, path=None, format=None):
        """Binary-safe HTTP proxy to an app listening inside the container's VM."""
        obj: Container = self.get_object()
        if not port:
            return Response("No port", status=status.HTTP_400_BAD_REQUEST)
        # DRF's format-suffix routing may peel a trailing extension (e.g.
        # ``openapi.json`` -> path="openapi", format="json"); stitch it back so the
        # real upstream path is preserved.
        if format:
            path = f"{path}.{format}" if path else format
        service = self._get_service(obj)
        return build_preview_response(request, obj, port, path, service)

    @action(detail=True, methods=["get"])
    def conversations(self, request, pk=None):
        """List the AI conversations stored in the VM (+ the active one)."""
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        return Response(convo.list_with_current(request.user, obj))

    @action(
        detail=True,
        methods=["get", "delete"],
        url_path=r"conversations/(?P<conversation_id>\d+)",
    )
    def conversation(self, request, pk=None, conversation_id=None):
        """GET the messages of one AI conversation, or DELETE it."""
        obj: Container = self.get_object()
        if not self._owner_quota(obj):
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        try:
            conv_id = int(cast(str, conversation_id))
        except (TypeError, ValueError):
            return Response(
                "Invalid conversation id", status=status.HTTP_400_BAD_REQUEST
            )

        if request.method == "DELETE":
            convo.delete_conversation(obj, conv_id)
            return Response(convo.list_with_current(request.user, obj))

        return Response(
            {
                "conversation_id": conv_id,
                "messages": convo.read_conversation(obj, conv_id),
            }
        )


class UserViewSet(viewsets.ViewSet):
    serializer_class = UserInfoSerializer

    @action(
        detail=False,
        methods=["get"],
        url_path="me",
        permission_classes=[permissions.IsAuthenticated],
    )
    def me(self, request):
        """Read-only user info"""
        user = request.user
        active_containers = Container.objects.filter(user=user).count()
        quota = getattr(user, "quota", None)

        payload = {
            "username": user.get_username(),
            "is_superuser": user.is_superuser,
            "active_containers": active_containers,
            "has_quota": bool(quota),
            "quota": quota,
        }

        audit_log_http(
            request,
            action="user.info",
            message="User info fetched",
            metadata={
                "active_containers": active_containers,
                "has_quota": bool(quota),
            },
            success=True,
        )

        serializer = self.serializer_class(instance=payload)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @method_decorator(csrf_exempt)
    @action(
        detail=False,
        methods=["post"],
        url_path="login",
        url_name="login",
        authentication_classes=[],
        permission_classes=[],
    )
    def login_(self, request):
        """Simple username/password login."""
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            audit_log_http(
                request,
                action="login",
                message="Login successful",
                metadata={"username": username},
                success=True,
            )
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        audit_log_http(
            request,
            action="login",
            message="Login failed: invalid credentials",
            metadata={"username": username},
            success=False,
        )
        return Response(
            {"error": "Invalid credentials"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="logout",
        url_name="logout",
        permission_classes=[permissions.IsAuthenticated],
    )
    def logout_(self, request):
        """Logout para usuarios autenticados."""
        audit_log_http(
            request,
            action="logout",
            message="Logout requested",
            success=True,
        )
        logout(request)
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class FileTemplateViewSet(viewsets.ModelViewSet):
    """
    CRUD for file templates and the "apply" action to push a template into a container.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FileTemplateSerializer
    queryset = FileTemplate.objects.all().order_by("-updated_at")

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(public=True)

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def apply(self, request, pk=None):
        """
        Apply a template to a container.
        """
        tpl = self.get_object()
        ser = ApplyTemplateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        container_model_id = data["container_id"]
        dest_path = data["dest_path"]
        clean = data["clean"]

        if request.user.is_superuser:
            container_obj = get_object_or_404(Container, pk=container_model_id)
        else:
            # Owners and collaborators may apply templates (it only writes files
            # into the VM). visible_containers_for covers both.
            container_obj = get_object_or_404(
                Container.visible_containers_for(request.user), pk=container_model_id
            )

        apply_template(container_obj, tpl, dest_path=dest_path, clean=clean)

        audit_log_http(
            request,
            action="template.apply",
            target_type="container",
            target_id=container_obj.pk,
            message="Template applied to container",
            metadata={
                "template_id": tpl.pk,
                "dest_path": dest_path,
                "clean": clean,
                "files_count": tpl.items.count(),
            },
            success=True,
        )

        payload = {
            "status": "applied",
            "template_id": tpl.pk,
            "container": container_obj.pk,
            "dest_path": dest_path,
            "files_count": tpl.items.count(),
        }

        return Response(ApplyTemplateResponseSerializer(payload).data)


class ContainerTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset to list and retrieve available container types.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerTypeSerializer

    def get_queryset(self):
        user = self.request.user
        quota = getattr(user, "quota", None)
        if quota and quota.allowed_types.exists():
            return quota.allowed_types.all()
        return ContainerType.objects.none()
