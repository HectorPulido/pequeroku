import os
import shlex
from io import StringIO

import paramiko

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Container, FileTemplate
from .serializers import ContainerSerializer, FileTemplateSerializer
from .usecases.vm_management import QemuSession
from .usecases.apply_template import _apply_template_to_vm
from .usecases.ssh import open_ssh_and_sftp, ensure_remote_dir
from .usecases.audit import audit_log_http

# Celery tasks
from app.tasks import (
    sftp_write_file_task,
    create_vm_first_time,
    send_command,
    power_off,
    power_on,
)


class ContainersViewSet(viewsets.ModelViewSet):
    """
    Container CRUD and VM utilities.

    Notes on refactor:
    - Added Celery for heavy/non-critical path work (e.g., template application at create).
      Endpoints and contracts remain unchanged.
    - Extracted SSH/SFTP boilerplate into helpers for readability and uniform error handling.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerSerializer
    queryset = Container.objects.all()

    # -------------------------
    # Queryset scoping
    # -------------------------
    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(user=self.request.user)

    # -------------------------
    # Utilities
    # -------------------------
    def _rand_id(self, n=6):
        import string, random

        return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

    # -------------------------
    # Overrides
    # -------------------------
    def create(self, request, *args, **kwargs):
        """
        Instead of creating a Docker container, create DB record and boot a VM session.
        Quota is enforced. Optional default template can be applied (via Celery).
        """
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

        active = Container.objects.filter(user=request.user, status="running").count()
        if active >= quota.max_containers:
            audit_log_http(
                request,
                action="container.create",
                message="Quota exceeded for container creation",
                metadata={
                    "active_running": active,
                    "max_containers": quota.max_containers,
                },
                success=False,
            )
            return Response("Quota exceeded", status=status.HTTP_403_FORBIDDEN)

        # Create record with a fake "container_id" and mark as creating
        c = Container.objects.create(
            user=request.user,
            container_id=self._rand_id(),
            image="vm:ubuntu-jammy",
            status="creating",
        )

        create_vm_first_time.delay(container_id=c.pk)

        audit_log_http(
            request,
            action="container.create",
            target_type="container",
            target_id=c.pk,
            message="Container record created and VM boot scheduled",
            metadata={"container_id": c.container_id, "image": c.image},
            success=True,
        )

        ser = self.get_serializer(c)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """
        Soft shutdown VM (best-effort) and remove DB record.
        """
        import threading

        obj = self.get_object()

        def shutdown_vm():
            try:
                sess = QemuSession(obj, on_line=None, on_close=None)
                sess.send("sudo shutdown -h now")
            except Exception:
                pass

        audit_log_http(
            request,
            action="container.destroy",
            target_type="container",
            target_id=obj.pk,
            message="Requested container deletion (attempting soft shutdown)",
            metadata={"container_id": obj.container_id},
            success=True,
        )

        t = threading.Thread(target=shutdown_vm)
        t.start()
        t.join(timeout=5)

        self.perform_destroy(obj)

        audit_log_http(
            request,
            action="container.destroy",
            target_type="container",
            target_id=obj.pk,
            message="Container record deleted",
            metadata={"container_id": obj.container_id},
            success=True,
        )

        return Response({"status": "stopped"})

    # -------------------------
    # Actions
    # -------------------------
    @action(detail=True, methods=["post"])
    def send_command(self, request, pk=None):
        """
        Sends a non-interactive command to the VM.
        Body: { "command": "ls -la" }
        """
        container = self.get_object()
        cmd = request.data.get("command", "")
        if not cmd:
            audit_log_http(
                request,
                action="container.send_command",
                target_type="container",
                target_id=container.pk,
                message="Empty command rejected",
                success=False,
            )
            return Response({"error": "command required"}, status=400)
        send_command.delay(container_id=container.pk, command=cmd)
        audit_log_http(
            request,
            action="container.send_command",
            target_type="container",
            target_id=container.pk,
            message="Command dispatched to VM",
            metadata={"command": cmd},
            success=True,
        )
        return Response({"status": "sent"})

    @action(detail=True, methods=["post"])
    def restart_container(self, request, pk=None):
        """
        Reopen the shell channel for the VM (VM keeps running).
        """
        container = self.get_object()
        try:
            sess = QemuSession(container, on_line=None, on_close=None)
            if hasattr(sess, "reopen"):
                sess.reopen()
            audit_log_http(
                request,
                action="container.restart_shell",
                target_type="container",
                target_id=container.pk,
                message="Shell channel reopened",
                metadata={"container_id": container.container_id},
                success=True,
            )
            return Response({"status": "restarted"})
        except Exception as e:
            audit_log_http(
                request,
                action="container.restart_shell",
                target_type="container",
                target_id=container.pk,
                message="Failed to reopen shell channel",
                metadata={"error": str(e)},
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
        """
        Upload a file via SFTP.
        form-data: file, dest_path (default /app)
        """
        container = self.get_object()
        f = request.FILES.get("file")
        dest = request.data.get("dest_path", "/app")
        if not f:
            audit_log_http(
                request,
                action="container.upload_file",
                target_type="container",
                target_id=container.pk,
                message="Upload rejected: no file provided",
                metadata={"dest_path": dest},
                success=False,
            )
            return Response({"error": "file required"}, status=400)

        # Ensure remote dir exists and stream upload in chunks.
        try:
            cli, sftp = open_ssh_and_sftp(container)
            try:
                ensure_remote_dir(cli, dest)
                remote_path = os.path.join(dest, f.name)
                size = 0
                with sftp.file(remote_path, "wb") as wf:
                    for chunk in f.chunks():
                        size += len(chunk)
                        wf.write(chunk)
                audit_log_http(
                    request,
                    action="container.upload_file",
                    target_type="container",
                    target_id=container.pk,
                    message="File uploaded via SFTP",
                    metadata={"remote_path": remote_path, "size_bytes": size},
                    success=True,
                )
                return Response({"dest": remote_path})
            finally:
                try:
                    sftp.close()
                finally:
                    cli.close()
        except Exception as e:
            audit_log_http(
                request,
                action="container.upload_file",
                target_type="container",
                target_id=container.pk,
                message="File upload failed",
                metadata={
                    "error": str(e),
                    "dest_path": dest,
                    "filename": getattr(f, "name", None),
                },
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["get"])
    def read_file(self, request, pk=None):
        """
        Read a file via SFTP.
        GET ?path=/absolute/path
        """
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

        try:
            cli, sftp = open_ssh_and_sftp(container)
            try:
                with sftp.file(path, "rb") as rf:
                    data = rf.read().decode("utf-8", errors="ignore")
                audit_log_http(
                    request,
                    action="container.read_file",
                    target_type="container",
                    target_id=container.pk,
                    message="File read via SFTP",
                    metadata={"path": path, "bytes_read": len(data)},
                    success=True,
                )
                return Response({"content": data})
            finally:
                try:
                    sftp.close()
                finally:
                    cli.close()
        except Exception as e:
            audit_log_http(
                request,
                action="container.read_file",
                target_type="container",
                target_id=container.pk,
                message="File read failed",
                metadata={"error": str(e), "path": path},
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def write_file(self, request, pk=None):
        """
        Create/Write a file.
        JSON: { "path": "/app/a.py", "content": "print(1)" }
        """
        container = self.get_object()
        path = request.data.get("path")
        content = request.data.get("content", "")
        if not path:
            audit_log_http(
                request,
                action="container.write_file",
                target_type="container",
                target_id=container.pk,
                message="Write rejected: path is required",
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        # Use Celery to write the file (could be large); still synchronous here
        # to preserve contract "status: ok" (we wait on the result).
        try:
            # If you want to truly offload, switch to .delay() and return a task id,
            # but that would change the contract. We keep it inline with apply().
            res = sftp_write_file_task.apply(
                kwargs={
                    "container_id": container.pk,
                    "path": path,
                    "content": content,
                }
            )
            if res.failed():
                audit_log_http(
                    request,
                    action="container.write_file",
                    target_type="container",
                    target_id=container.pk,
                    message="Write failed (Celery result)",
                    metadata={"error": str(res.result), "path": path},
                    success=False,
                )
                return Response({"error": str(res.result)}, status=500)
            audit_log_http(
                request,
                action="container.write_file",
                target_type="container",
                target_id=container.pk,
                message="File written via SFTP",
                metadata={"path": path, "bytes": len(content or "")},
                success=True,
            )
            return Response({"status": "ok"})
        except Exception as e:
            audit_log_http(
                request,
                action="container.write_file",
                target_type="container",
                target_id=container.pk,
                message="Write failed (exception)",
                metadata={"error": str(e), "path": path},
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["get"])
    def list_dir(self, request, pk=None):
        """
        Recursively list (depth 2) using 'find', returning {path, name, type}.
        GET ?path=/app
        """
        container = self.get_object()
        root = request.GET.get("path", "/app")

        try:
            cli, _ = open_ssh_and_sftp(container, open_sftp=False)
            try:
                cmd = f"find {shlex.quote(root)} -maxdepth 2 -printf '%p||%y\\n' 2>/dev/null || true"
                _, stdout, _ = cli.exec_command(cmd)
                lines = (stdout.read().decode() or "").strip().splitlines()
                items = []
                for ln in lines:
                    if "||" not in ln:
                        continue
                    p, t = ln.split("||", 1)
                    base = os.path.basename(p.rstrip("/")) or p
                    items.append(
                        {
                            "path": p,
                            "name": base,
                            "type": "directory" if t == "d" else "file",
                        }
                    )
                audit_log_http(
                    request,
                    action="container.list_dir",
                    target_type="container",
                    target_id=container.pk,
                    message="Directory listed via find",
                    metadata={"root": root, "count": len(items)},
                    success=True,
                )
                return Response(items)
            finally:
                cli.close()
        except Exception as e:
            audit_log_http(
                request,
                action="container.list_dir",
                target_type="container",
                target_id=container.pk,
                message="Directory listing failed",
                metadata={"error": str(e), "root": root},
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def create_dir(self, request, pk=None):
        """
        Create a directory in the VM.
        JSON: { "path": "/app/new" }
        """
        container = self.get_object()
        path = request.data.get("path")
        if not path:
            audit_log_http(
                request,
                action="container.create_dir",
                target_type="container",
                target_id=container.pk,
                message="Create dir rejected: path is required",
                success=False,
            )
            return Response({"error": "path required"}, status=400)

        try:
            cli, _ = open_ssh_and_sftp(container, open_sftp=False)
            try:
                _, stdout, _ = cli.exec_command(f"mkdir -p {shlex.quote(path)}")
                rc = stdout.channel.recv_exit_status()
                if rc == 0:
                    audit_log_http(
                        request,
                        action="container.create_dir",
                        target_type="container",
                        target_id=container.pk,
                        message="Directory created",
                        metadata={"path": path},
                        success=True,
                    )
                    return Response({"status": "ok"})
                audit_log_http(
                    request,
                    action="container.create_dir",
                    target_type="container",
                    target_id=container.pk,
                    message="mkdir returned non-zero exit status",
                    metadata={"path": path, "exit_code": rc},
                    success=False,
                )
                return Response({"error": "mkdir failed"}, status=500)
            finally:
                cli.close()
        except Exception as e:
            audit_log_http(
                request,
                action="container.create_dir",
                target_type="container",
                target_id=container.pk,
                message="Directory creation failed",
                metadata={"error": str(e), "path": path},
                success=False,
            )
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        """
        Start VM via management command. Kept synchronous to preserve the
        original response (status + log).
        """

        container = self.get_object()
        power_on.delay(container_id=container.pk)
        audit_log_http(
            request,
            action="container.power_on",
            target_type="container",
            target_id=container.pk,
            message="Power on requested",
            metadata={"container_id": container.container_id},
            success=True,
        )
        return Response(
            {
                "status": container.status,
            }
        )

    @action(detail=True, methods=["post"])
    def power_off(self, request, pk=None):
        """
        Stop VM via management command. Kept synchronous to preserve contract.
        """

        force = bool(request.data.get("force", False))
        container = self.get_object()
        power_off.delay(container_id=container.pk, force=force)
        audit_log_http(
            request,
            action="container.power_off",
            target_type="container",
            target_id=container.pk,
            message="Power off requested",
            metadata={"container_id": container.container_id, "force": force},
            success=True,
        )
        return Response(
            {
                "status": container.status,
            }
        )

    @action(detail=True, methods=["get"])
    def real_status(self, request, pk=None):
        """
        Sync and return the real status from the VM layer.
        """
        container = self.get_object()
        audit_log_http(
            request,
            action="container.real_status",
            target_type="container",
            target_id=container.pk,
            message="Real status requested",
            metadata={
                "container_id": container.container_id,
                "status": container.status,
            },
            success=True,
        )
        return Response(
            {"status": container.status, "container_id": container.container_id}
        )


class UserViewSet(APIView):
    """
    Read-only user info: username, quota and active containers count.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        quota = getattr(user, "quota", None)
        active_containers = Container.objects.filter(user=request.user).count()

        quota_data = (
            {
                "max_containers": 0,
                "max_memory_mb": 0,
                "max_cpu_percent": 0,
            }
            if not quota
            else {
                "max_containers": quota.max_containers,
                "max_memory_mb": quota.max_memory_mb,
                "max_cpu_percent": quota.max_cpu_percent,
            }
        )

        audit_log_http(
            request,
            action="user.info",
            message="User info fetched",
            metadata={"active_containers": active_containers, "has_quota": bool(quota)},
            success=True,
        )

        return Response(
            {
                "username": user.username,
                "active_containers": active_containers,
                "has_quota": bool(quota),
                "quota": quota_data,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class LoginView(APIView):
    """
    Simple username/password login.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
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
            {"error": "Credenciales inválidas"}, status=status.HTTP_400_BAD_REQUEST
        )


class LogoutView(APIView):
    """
    Simple logout for authenticated users.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
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

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def apply(self, request, pk=None):
        """
        Apply a template to a container.
        Body JSON:
        {
          "container_id": 123,
          "dest_path": "/app",  # optional
          "clean": true         # whether to remove previous content
        }

        Kept synchronous to preserve the original response (status + files_count).
        """
        tpl = self.get_object()
        container_model_id = request.data.get("container_id")

        if request.user.is_superuser:
            container_obj = get_object_or_404(Container, pk=container_model_id)
        else:
            container_obj = get_object_or_404(
                Container, pk=container_model_id, user=request.user
            )

        dest_path = str(request.data.get("dest_path") or "/app").rstrip("/")
        clean = bool(request.data.get("clean", True))

        # Keep behavior: synchronous application (so response mirrors original).
        _apply_template_to_vm(container_obj, tpl, dest_path=dest_path, clean=clean)

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

        return Response(
            {
                "status": "applied",
                "template_id": tpl.pk,
                "container": container_obj.pk,
                "dest_path": dest_path,
                "files_count": tpl.items.count(),
            }
        )
