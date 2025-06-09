import io
import re
import tarfile

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Container, ResourceQuota
from .serializers import ContainerSerializer
from .session import DockerSession

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

    def create(self, request, *args, **kwargs):
        try:
            quota: ResourceQuota = request.user.quota
        except Exception as e:
            raise PermissionDenied(
                "You have not assigned quota, contact with the admin"
            ) from e

        active_count = Container.objects.filter(
            user=request.user, status="running"
        ).count()
        if active_count >= quota.max_containers:
            raise ValidationError(
                f"You reach your active containers limit {quota.max_containers}"
            )

        mem_limit = f"{quota.max_memory_mb}m"  # ej. "256m"
        cpu_quota = int(quota.max_cpu_percent * 1000)

        cont = settings.DOCKER_CLIENT.containers.run(
            "ubuntu:latest",
            command="/bin/bash",
            detach=True,
            tty=True,
            stdin_open=True,
            mem_limit=mem_limit,
            cpu_period=100000,
            cpu_quota=cpu_quota,
            network_mode="bridge",
            dns=["8.8.8.8", "8.8.4.4"],
        )
        obj = Container.objects.create(
            user=request.user, container_id=cont.id, status="running"
        )
        SESSIONS[obj.pk] = DockerSession(obj, settings.DOCKER_CLIENT)
        return Response(ContainerSerializer(obj).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        try:
            c = settings.DOCKER_CLIENT.containers.get(obj.container_id)
            c.stop()
            c.remove()
            obj.status = "stopped"
            obj.save()
            sess = SESSIONS.pop(obj.id, None)
            settings.REDIS_CLIENT.delete(sess.key)
            if sess:
                sess.sock.close()
            self.perform_destroy(obj)
            return Response({"status": "stopped"})
        except Exception as e:
            self.perform_destroy(obj)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def send_command(self, request, pk=None):
        """
        Returns all cards of the board.
        """
        obj = get_object_or_404(Container, pk=pk, user=request.user)
        cmd = request.data.get("command")
        if not cmd:
            return Response(
                {"error": "No command provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        sess = SESSIONS.get(pk) or DockerSession(obj, settings.DOCKER_CLIENT)
        SESSIONS[pk] = sess

        print("Command: ", cmd)
        if cmd.strip() == "clear":
            settings.REDIS_CLIENT.delete(sess.key)

        if cmd.strip() == "ctrlc":
            cmd = "\x04"

        if cmd.strip() == "ctrld":
            cmd = "\x03"

        sess.send(cmd)
        return Response({"status": "sent"})

    @action(detail=True, methods=["get"])
    def read_logs(self, request, pk):
        key = f"logs:{pk}"
        dirty = settings.REDIS_CLIENT.lrange(key, 0, -1)

        ansi_escape = re.compile(
            r"(?:" r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07" r")"
        )

        cleaned = []
        for s in dirty:
            no_ansi = ansi_escape.sub("", s)
            no_ansi = no_ansi.replace("\x07", "")
            if no_ansi.strip():
                cleaned.append(no_ansi)

        return Response({"logs": cleaned})

    @action(detail=True, methods=["post"])
    def restart_container(self, request, pk=None):
        obj = get_object_or_404(Container, pk=pk, user=request.user)
        try:
            del SESSIONS[obj.pk]
        except KeyError:
            ...
        sess = DockerSession(obj, settings.DOCKER_CLIENT)
        SESSIONS[pk] = sess
        settings.REDIS_CLIENT.delete(sess.key)

        return Response({"status": "stopped"})

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def upload_file(self, request, pk=None):
        """
        Recibe un archivo (multipart/form-data) y lo copia dentro del contenedor.
        Parámetros opcionales en JSON: 'dest_path' (ruta destino en el contenedor).
        """
        obj = self.get_object()
        container = settings.DOCKER_CLIENT.containers.get(obj.container_id)

        # Archivo subido
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "No se ha enviado ningún archivo."}, status=400)

        # Ruta destino en el contenedor (por defecto /app)
        dest_path = request.data.get("dest_path", "/")

        # Armamos un tar en memoria con el fichero
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            info = tarfile.TarInfo(name=upload.name)
            upload.seek(0, io.SEEK_END)
            info.size = upload.tell()
            upload.seek(0)
            tar.addfile(info, upload.file)
        tar_stream.seek(0)

        # Copiamos el tar dentro del contenedor
        success = container.put_archive(dest_path, tar_stream.read())
        if not success:
            return Response({"error": "Fallo al copiar el archivo."}, status=500)

        return Response({"status": "archivo copiado", "dest": dest_path})


class UserViewSet(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        quota = None
        try:
            quota = user.quota
        except Exception:
            ...
        active_containers = Container.objects.filter(
            user=request.user, status="running"
        ).count()

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
