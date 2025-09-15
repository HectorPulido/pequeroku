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
    ApplyAICodeRequestSerializer,
    ApplyAICodeResponseSerializer,
)
from .models import Container, Node, FileTemplate
from .vm_client import VMServiceClient, VMCreate, VMAction, VMUploadFiles, VMFile

from .templates import (
    apply_template,
    first_start_of_container,
    apply_ai_generated_project,
)

from .mixin import VMSyncMixin


class ContainersViewSet(viewsets.ModelViewSet, VMSyncMixin):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerSerializer
    queryset = Container.objects.all()

    def get_queryset(self):
        qs = super().get_queryset().select_related("node")
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(user=user)

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
        # Quota check
        quota = getattr(request.user, "quota", None)
        if not quota:
            audit_log_http(
                request,
                action="container.create",
                message="Create attempt without assigned quota",
                success=False,
            )
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        if not quota.can_create_container(request.user):
            audit_log_http(
                request,
                action="container.create",
                message="Quota exceeded for container creation",
                metadata={
                    "max_containers": quota.max_containers,
                },
                success=False,
            )
            return Response("Quota exceeded", status=status.HTTP_403_FORBIDDEN)

        node = Node.get_random_node()

        if not node:
            return Response(
                "No available nodes", status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        service = VMServiceClient(
            base_url=str(node.node_host),
            token=str(node.auth_token),
        )

        vm = service.create_vm(
            VMCreate(
                vcpus=quota.vcpus,
                mem_mib=quota.max_memory_mb,
                disk_gib=quota.default_disk_gib,
            )
        )

        c = Container.objects.create(
            user=request.user,
            container_id=vm["id"],
            base_image="",
            status="creating",
            memory_mb=quota.max_memory_mb,
            vcpus=quota.vcpus,
            disk_gib=quota.default_disk_gib,
            node=node,
        )

        audit_log_http(
            request,
            action="container.create",
            target_type="container",
            target_id=c.pk,
            message="Container record created and VM boot scheduled",
            metadata={"container_id": c.container_id, "image": c.base_image},
            success=True,
        )

        ser = self.get_serializer(c)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
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
    def delete_path(self, request, pk=None):
        obj: Container = self.get_object()
        path = request.data.get("path")

        if not path:
            audit_log_http(
                request,
                action="container.delete_file",
                target_type="container",
                target_id=obj.pk,
                message="Deletion rejected: no path provided",
                metadata={"path": path},
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        service = self._get_service(obj)
        response = service.execute_sh(str(obj.container_id), f"rm -rf {path}")

        audit_log_http(
            request,
            action="container.delete_file",
            target_type="container",
            target_id=obj.pk,
            message="Deletion success",
            metadata={"path": path, "response": response},
            success=True,
        )

        return Response(response)

    @action(detail=True, methods=["post"])
    def move_path(self, request, pk=None):
        obj: Container = self.get_object()
        src = request.data.get("src")
        dest = request.data.get("dest")

        if not src or not dest:
            audit_log_http(
                request,
                action="container.change_path",
                target_type="container",
                target_id=obj.pk,
                message="Change path rejected, not src or dest",
                metadata={"src": src, "dest": dest},
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        service = self._get_service(obj)
        response = service.execute_sh(str(obj.container_id), f"mv -f {src} {dest}")

        audit_log_http(
            request,
            action="container.change_path",
            target_type="container",
            target_id=obj.pk,
            message="Deletion success",
            metadata={"src": src, "dest": dest, "response": response},
            success=True,
        )

        return Response(response)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
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
        try:
            response = service.upload_files(
                str(obj.container_id),
                VMUploadFiles(
                    dest_path=dest,
                    clean=False,
                    files=[VMFile(path=f.name, content=f.read().decode("utf-8"))],
                ),
            )
        except:
            return Response({"error": "file required to be a text one"}, status=400)

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
    def read_file(self, request, pk=None):
        container = self.get_object()
        path = request.GET.get("path")

        if not path:
            audit_log_http(
                request,
                action="container.read_file",
                target_type="container",
                target_id=container.pk,
                message="Read rejected: path is required",
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        obj: Container = self.get_object()
        service = self._get_service(obj)
        response = service.read_file(str(obj.container_id), path)

        audit_log_http(
            request,
            action="container.read_file",
            target_type="container",
            target_id=container.pk,
            message="File read via SFTP",
            metadata={"path": path, "bytes_read": response.get("length", 0)},
            success=True,
        )

        if not response.get("found", False):
            first_start_of_container(obj)
            return Response({"error": "File not found"}, status=404)

        return Response(response)

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def create_dir(self, request, pk=None):
        path = request.data.get("path")
        obj: Container = self.get_object()

        if not path:
            audit_log_http(
                request,
                action="container.create_dir",
                target_type="container",
                target_id=obj.pk,
                message="Create dir rejected: path is required",
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        service = self._get_service(obj)
        service.create_dir(
            str(obj.container_id),
            path,
        )
        audit_log_http(
            request,
            action="container.create_dir",
            target_type="container",
            target_id=obj.pk,
            message="Directory created",
            metadata={"path": path},
            success=True,
        )
        return Response({"status": "ok"})

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def write_file(self, request, pk=None):
        path = request.data.get("path")
        content = request.data.get("content", "")
        obj: Container = self.get_object()

        if not path:
            audit_log_http(
                request,
                action="container.write_file",
                target_type="container",
                target_id=obj.pk,
                message="Write rejected: path is required",
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        service = self._get_service(obj)
        service.upload_files(
            str(obj.container_id),
            VMUploadFiles(
                dest_path="/",
                clean=False,
                files=[VMFile(path=path, content=content)],
            ),
        )
        audit_log_http(
            request,
            action="container.write_file",
            target_type="container",
            target_id=obj.pk,
            message="File written via SFTP",
            metadata={"path": path, "bytes": len(content or "")},
            success=True,
        )

        return Response({"status": "ok"})

    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        obj: Container = self.get_object()
        if obj.status != "running":
            return Response({"error": "VM off"}, status=400)

        service = self._get_service(obj)
        response = service.statistics(str(obj.container_id))
        return Response(response)

    @action(detail=True, methods=["get"])
    def list_dir(self, request, pk=None):
        root = request.GET.get("path", "/app")
        obj: Container = self.get_object()
        service = self._get_service(obj)
        response = service.list_dir(str(obj.container_id), root)

        audit_log_http(
            request,
            action="container.list_dir",
            target_type="container",
            target_id=obj.pk,
            message="Directory listed via find",
            metadata={"root": root, "count": len(response)},
            success=True,
        )
        return Response(response)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        obj: Container = self.get_object()
        service = self._get_service(obj)
        service.action_vm(
            str(obj.container_id), action=VMAction(action="start", cleanup_disks=False)
        )
        audit_log_http(
            request,
            action="container.power_on",
            target_type="container",
            target_id=obj.pk,
            message="Power on requested",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        return Response({"status": "starting..."})

    @action(detail=True, methods=["post"])
    def power_off(self, request, pk=None):
        obj: Container = self.get_object()
        service = self._get_service(obj)
        service.action_vm(
            str(obj.container_id), action=VMAction(action="stop", cleanup_disks=False)
        )
        audit_log_http(
            request,
            action="container.power_off",
            target_type="container",
            target_id=obj.pk,
            message="Power off requested",
            metadata={"container_id": obj.container_id},
            success=True,
        )
        return Response({"status": "stoping..."})

    @action(detail=True, methods=["post"])
    def restart_container(self, request, pk=None):
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

    @action(detail=False, methods=["post"], parser_classes=[JSONParser])
    def apply_ai_generated_code(self, request):
        """
        Apply ai generated code to a container.
        """
        ser = ApplyAICodeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        container_model_id = data["container_id"]
        dest_path = data["dest_path"]
        clean = data["clean"]
        content = data["content"]

        if request.user.is_superuser:
            container_obj = get_object_or_404(Container, pk=container_model_id)
        else:
            container_obj = get_object_or_404(
                Container, pk=container_model_id, user=request.user
            )

        apply_ai_generated_project(
            container_obj, content, dest_path=dest_path, clean=clean
        )

        audit_log_http(
            request,
            action="template.apply",
            target_type="container",
            target_id=container_obj.pk,
            message="AI code applied to container",
            metadata={
                "dest_path": dest_path,
                "clean": clean,
            },
            success=True,
        )

        payload = {
            "status": "applied",
            "container": container_obj.pk,
            "dest_path": dest_path,
        }

        return Response(ApplyAICodeResponseSerializer(payload).data)
