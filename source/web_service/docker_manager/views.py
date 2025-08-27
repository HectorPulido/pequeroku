import io
import os
import shlex
import tarfile
from io import BytesIO

import paramiko

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import get_object_or_404

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Container, FileTemplate, ResourceQuota
from .serializers import ContainerSerializer, FileTemplateSerializer
from .session import QemuSession

from .usecases.apply_template import _apply_template_to_vm

SESSIONS = {}


class ContainersViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContainerSerializer
    queryset = Container.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(user=self.request.user)

    def _rand_id(self, n=6):
        import string, random

        return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

    def create(self, request, *args, **kwargs):
        # En vez de crear un contenedor Docker, creamos registro y boot de VM en session
        # Verificamos cuota
        try:
            quota = request.user.quota
        except Exception:
            return Response("No quota assigned", status=status.HTTP_403_FORBIDDEN)
        active = Container.objects.filter(user=request.user, status="running").count()
        if active >= quota.max_containers:
            return Response("Quota exceeded", status=status.HTTP_403_FORBIDDEN)

        c = Container.objects.create(
            user=request.user,
            container_id=self._rand_id(),
            image="vm:ubuntu-jammy",
            status="creating",
        )
        sess = QemuSession(c, on_line=None, on_close=None)
        SESSIONS[c.pk] = sess

        slug = getattr(settings, "DEFAULT_TEMPLATE_SLUG", None)
        dest = getattr(settings, "DEFAULT_TEMPLATE_DEST", "/app")
        clean = getattr(settings, "DEFAULT_TEMPLATE_CLEAN", True)
        if slug:
            try:
                tpl = FileTemplate.objects.get(slug=slug)
                _apply_template_to_vm(c, tpl, dest_path=dest, clean=clean)
            except FileTemplate.DoesNotExist:
                try:
                    tpl = FileTemplate.objects.order_by("-updated_at").first()
                    if tpl:
                        _apply_template_to_vm(c, tpl, dest_path=dest, clean=clean)
                except Exception:
                    pass

        ser = self.get_serializer(c)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # No mantenemos PID del QEMU aquí; cerramos la shell (si hay) y marcamos detenido.
        sess = SESSIONS.pop(obj.pk, None)
        if sess:
            try:
                # envío de shutdown a la VM (suave)
                sess.send("sudo shutdown -h now")
            except Exception:
                ...
        obj.status = "stopped"
        obj.save(update_fields=["status"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def send_command(self, request, pk=None):
        """
        Envía un comando “no interactivo” por REST (opcional: lo mantenemos para compatibilidad).
        Nota: el IDE ahora usa WebSocket. Aquí simplemente abrimos/reutilizamos sesión y mandamos texto.
        Body: { "command": "ls -la" }
        """
        container = self.get_object()
        cmd = request.data.get("command", "")
        if not cmd:
            return Response({"error": "command required"}, status=400)
        sess = SESSIONS.get(container.pk)
        if not sess:
            sess = QemuSession(container, None)
            SESSIONS[container.pk] = sess
        try:
            sess.send(cmd)
            return Response({"status": "sent"})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def restart_container(self, request, pk=None):
        """
        Reabre el canal del shell (la VM sigue viva).
        """
        container = self.get_object()
        sess = SESSIONS.get(container.pk)
        if not sess:
            sess = QemuSession(container, None)
            SESSIONS[container.pk] = sess
        else:
            sess.reopen()
        return Response({"status": "restarted"})

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
        """
        Sube un archivo por SFTP a la VM
        form-data: file, dest_path (default /app)
        """
        container = self.get_object()
        f = request.FILES.get("file")
        dest = request.data.get("dest_path", "/app")
        if not f:
            return Response({"error": "file required"}, status=400)

        sess = SESSIONS.get(container.pk)
        if not sess:
            sess = QemuSession(container, None)
            SESSIONS[container.pk] = sess

        # hacemos upload vía SFTP
        try:
            # reabrimos un cliente temporal para SFTP
            k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # puerto desde container_id: qemu:<port>
            port = int(container.container_id.split(":")[1])
            cli.connect(
                "127.0.0.1",
                port=port,
                username=settings.VM_SSH_USER,
                pkey=k,
                look_for_keys=False,
            )
            sftp = cli.open_sftp()
            # asegúrate de que dest exista
            try:
                sess.send(f"mkdir -p {shlex.quote(dest)}")
            except Exception:
                ...
            remote_path = os.path.join(dest, f.name)
            with sftp.file(remote_path, "wb") as wf:
                for chunk in f.chunks():
                    wf.write(chunk)
            sftp.close()
            cli.close()
            return Response({"dest": remote_path})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["get"])
    def read_file(self, request, pk=None):
        """
        Lee un archivo por SFTP
        GET ?path=/ruta
        """
        container = self.get_object()
        path = request.GET.get("path")
        if not path:
            return Response({"error": "path required"}, status=400)
        try:
            k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            port = int(container.container_id.split(":")[1])
            cli.connect(
                "127.0.0.1",
                port=port,
                username=settings.VM_SSH_USER,
                pkey=k,
                look_for_keys=False,
            )
            sftp = cli.open_sftp()
            with sftp.file(path, "rb") as rf:
                data = rf.read().decode("utf-8", errors="ignore")
            sftp.close()
            cli.close()
            return Response({"content": data})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def write_file(self, request, pk=None):
        """
        Crea/Escribe un archivo
        JSON: { "path": "/app/a.py", "content": "print(1)" }
        """
        container = self.get_object()
        path = request.data.get("path")
        content = request.data.get("content", "")
        if not path:
            return Response({"error": "path required"}, status=400)
        try:
            k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            port = int(container.container_id.split(":")[1])
            cli.connect(
                "127.0.0.1",
                port=port,
                username=settings.VM_SSH_USER,
                pkey=k,
                look_for_keys=False,
            )
            sftp = cli.open_sftp()
            # asegurar directorio
            dirn = os.path.dirname(path)
            if dirn:
                # crea por shell (más simple)
                stdin, stdout, stderr = cli.exec_command(
                    f"mkdir -p {shlex.quote(dirn)}"
                )
                stdout.channel.recv_exit_status()
            with sftp.file(path, "wb") as wf:
                wf.write(content.encode("utf-8"))
            sftp.close()
            cli.close()
            return Response({"status": "ok"})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["get"])
    def list_dir(self, request, pk=None):
        """
        Lista recursivamente vía 'find' (como antes), devolviendo {path, name, type}
        GET ?path=/app
        """
        container = self.get_object()
        root = request.GET.get("path", "/app")
        try:
            k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            port = int(container.container_id.split(":")[1])
            cli.connect(
                "127.0.0.1",
                port=port,
                username=settings.VM_SSH_USER,
                pkey=k,
                look_for_keys=False,
            )
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
            cli.close()
            return Response(items)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def create_dir(self, request, pk=None):
        """
        Crea carpeta en la VM
        JSON: { "path": "/app/nueva" }
        """
        container = self.get_object()
        path = request.data.get("path")
        if not path:
            return Response({"error": "path required"}, status=400)
        try:
            k = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            port = int(container.container_id.split(":")[1])
            cli.connect(
                "127.0.0.1",
                port=port,
                username=settings.VM_SSH_USER,
                pkey=k,
                look_for_keys=False,
            )
            _, stdout, _ = cli.exec_command(f"mkdir -p {shlex.quote(path)}")
            rc = stdout.channel.recv_exit_status()
            cli.close()
            if rc == 0:
                return Response({"status": "ok"})
            return Response({"error": "mkdir failed"}, status=500)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=True, methods=["post"])
    def power_on(self, request, pk=None):
        from io import StringIO
        from django.core.management import call_command

        buf = StringIO()
        try:
            call_command("vmctl", "start", str(pk), stdout=buf)
            return Response({"status": "running", "log": buf.getvalue()})
        except Exception as e:
            return Response({"error": str(e), "log": buf.getvalue()}, status=500)

    @action(detail=True, methods=["post"])
    def power_off(self, request, pk=None):
        from io import StringIO
        from django.core.management import call_command

        force = bool(request.data.get("force", False))
        buf = StringIO()
        try:
            args = ["stop", str(pk)] + (["--force"] if force else [])
            call_command("vmctl", *args, stdout=buf)
            # lee estado actualizado
            container = self.get_object()
            return Response({"status": container.status, "log": buf.getvalue()})
        except Exception as e:
            return Response({"error": str(e), "log": buf.getvalue()}, status=500)

    @action(detail=True, methods=["get"])
    def real_status(self, request, pk=None):
        from io import StringIO
        from django.core.management import call_command

        buf = StringIO()
        try:
            call_command("vmctl", "sync", "--id", str(pk), stdout=buf)
        except Exception:
            ...
        container = self.get_object()
        return Response(
            {"status": container.status, "container_id": container.container_id}
        )


class UserViewSet(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        quota = None
        try:
            quota = user.quota
        except Exception:
            ...
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
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class FileTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FileTemplateSerializer
    queryset = FileTemplate.objects.all().order_by("-updated_at")

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def apply(self, request, pk=None):
        """
        Aplica el template a un contenedor.
        Body JSON:
        {
          "container_id": 123,     # id del modelo Container
          "dest_path": "/app",     # opcional (default /app)
          "clean": true            # borra contenido previo
        }
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
