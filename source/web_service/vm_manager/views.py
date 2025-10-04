import os
import base64
from dataclasses import asdict
from typing import cast

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from internal_config.audit import audit_log_http

from .serializers import (
    ContainerSerializer,
    UserInfoSerializer,
    FileTemplateSerializer,
    ApplyTemplateRequestSerializer,
    ApplyTemplateResponseSerializer,
    ContainerTypeSerializer,
)
from .models import Container, FileTemplate, Node, ContainerType
from .vm_client import VMServiceClient, VMCreate, VMAction, VMUploadFiles, VMFile

from .templates import (
    apply_template,
)

from .mixin import VMSyncMixin


class ContainersViewSet(viewsets.ModelViewSet, VMSyncMixin):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerSerializer
    queryset = Container.objects.all()

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return Container.objects.none()

        if user.is_superuser:
            return super().get_queryset().select_related("node")

        return Container.visible_containers_for(user)

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

        vcpus = int(ct.vcpus)
        mem_mb = int(ct.memory_mb)
        disk_gib = int(ct.disk_gib)

        node = self.choose_node(vcpus, mem_mb)

        warn_msg = None
        if not node:
            node = Node.get_random_node()
            warn_msg = "No available nodes with enough capacity; proceeding on best-effort node"
            print(f"requested vcpus: {vcpus}, requested mem_mb: {mem_mb}")
            print(warn_msg)

        if not node:
            return Response(
                "No node available",
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        service = VMServiceClient(node)

        vm = service.create_vm(
            VMCreate(
                vcpus=vcpus,
                mem_mib=mem_mb,
                disk_gib=disk_gib,
            )
        )

        c = Container.objects.create(
            name=ct_name,
            user=request.user,
            container_id=vm["id"],
            base_image="",
            status="creating",
            memory_mb=mem_mb,
            vcpus=vcpus,
            disk_gib=disk_gib,
            node=node,
            container_type=ct,
        )

        metadata: dict[str, object] = {
            "container_id": str(c.container_id),
            "image": str(c.base_image),
            "container_type": str(ct.pk),
            "credits_cost": getattr(ct, "credits_cost", None),
        }

        audit_log_http(
            request,
            action="container.create",
            target_type="container",
            target_id=c.pk,
            message="Container record created and VM boot scheduled",
            metadata=metadata,
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

    def destroy(self, request, *args, **kwargs):
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()
        service = self._get_service(obj)
        try:
            service.delete_vm(obj.container_id)
        except Exception as e:
            print("Could not stop vm, deleting anyway", e)

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

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        f = request.FILES.get("file")
        dest = request.data.get("dest_path", "/app")
        obj: Container = self.get_object()

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

    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
        if obj.status != "running":
            return Response({"error": "VM off"}, status=400)

        service = self._get_service(obj)
        response = service.statistics(str(obj.container_id))
        return Response(response)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
        service = self._get_service(obj)
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
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
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
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
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
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
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
        quota = self._check_quota(request)
        if not quota:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        obj: Container = self.get_object()
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
            container_obj = get_object_or_404(
                Container, pk=container_model_id, user=request.user
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
