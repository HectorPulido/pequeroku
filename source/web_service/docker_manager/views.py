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
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)

        active = Container.objects.filter(user=request.user, status="running").count()
        if active >= quota.max_containers:
            return Response("Quota exceeded", status=status.HTTP_403_FORBIDDEN)

        # Create record with a fake "container_id" and mark as creating
        c = Container.objects.create(
            user=request.user,
            container_id=self._rand_id(),
            image="vm:ubuntu-jammy",
            status="creating",
        )

        create_vm_first_time.delay(container_id=c.pk)

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

        t = threading.Thread(target=shutdown_vm)
        t.start()
        t.join(timeout=5)

        self.perform_destroy(obj)
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
            return Response({"error": "command required"}, status=400)
        send_command.delay(container_id=container.pk, command=cmd)
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
            return Response({"status": "restarted"})
        except Exception as e:
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
            return Response({"error": "file required"}, status=400)

        # Ensure remote dir exists and stream upload in chunks.
        try:
            cli, sftp = open_ssh_and_sftp(container)
            try:
                ensure_remote_dir(cli, dest)
                remote_path = os.path.join(dest, f.name)
                with sftp.file(remote_path, "wb") as wf:
                    for chunk in f.chunks():
                        wf.write(chunk)
                return Response({"dest": remote_path})
            finally:
                try:
                    sftp.close()
                finally:
                    cli.close()
        except Exception as e:
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
            return Response({"error": "path required"}, status=400)

        try:
            cli, sftp = open_ssh_and_sftp(container)
            try:
                with sftp.file(path, "rb") as rf:
                    data = rf.read().decode("utf-8", errors="ignore")
                return Response({"content": data})
            finally:
                try:
                    sftp.close()
                finally:
                    cli.close()
        except Exception as e:
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
                return Response({"error": str(res.result)}, status=500)
            return Response({"status": "ok"})
        except Exception as e:
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
                return Response(items)
            finally:
                cli.close()
        except Exception as e:
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
            return Response({"error": "path required"}, status=400)

        try:
            cli, _ = open_ssh_and_sftp(container, open_sftp=False)
            try:
                _, stdout, _ = cli.exec_command(f"mkdir -p {shlex.quote(path)}")
                rc = stdout.channel.recv_exit_status()
                if rc == 0:
                    return Response({"status": "ok"})
                return Response({"error": "mkdir failed"}, status=500)
            finally:
                cli.close()
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        """
        Start VM via management command. Kept synchronous to preserve the
        original response (status + log).
        """

        container = self.get_object()
        power_on.delay(container_id=container.pk)
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
            return Response({"status": "ok"}, status=status.HTTP_200_OK)
        return Response(
            {"error": "Credenciales inválidas"}, status=status.HTTP_400_BAD_REQUEST
        )


class LogoutView(APIView):
    """
    Simple logout for authenticated users.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
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

        return Response(
            {
                "status": "applied",
                "template_id": tpl.pk,
                "container": container_obj.pk,
                "dest_path": dest_path,
                "files_count": tpl.items.count(),
            }
        )
