import os
from django.conf import settings
from docker.errors import ImageNotFound
import threading
from typing import Callable, Optional

from docker import DockerClient

from .models import Container


class DockerSession:
    def __init__(
        self,
        container_obj: Container,
        docker_client: DockerClient,
        on_line: Optional[Callable[[str], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.container_id = container_obj.container_id
        self.client = docker_client
        self._on_line = on_line
        self._on_close = on_close
        self.alive = False
        self._open_exec()

    def _open_exec(self):
        res = self.client.api.exec_create(
            self.container_id, cmd=["/bin/bash"], stdin=True, tty=True
        )
        self.exec_id = res["Id"]
        sock = self.client.api.exec_start(
            self.exec_id, tty=True, detach=False, socket=True
        )
        self.sock = sock._sock
        self.alive = True

        def reader():
            try:
                while True:
                    data = self.sock.recv(4096)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="ignore")
                    if self._on_line:
                        for line in text.splitlines():
                            if line.strip():
                                try:
                                    self._on_line(line)
                                except Exception:
                                    ...
            except Exception:
                ...
            finally:
                self.alive = False
                try:
                    self.sock.close()
                except Exception:
                    ...
                if self._on_close:
                    try:
                        self._on_close()
                    except Exception:
                        ...

        t = threading.Thread(target=reader, daemon=True)
        t.start()

    def reopen(self):
        # Cierra si algo quedara abierto y abre nuevo exec
        try:
            self.close()
        except Exception:
            ...
        self._open_exec()

    def is_alive(self) -> bool:
        return bool(self.alive)

    def set_on_line(self, cb: Optional[Callable[[str], None]]):
        self._on_line = cb

    def set_on_close(self, cb: Optional[Callable[[], None]]):
        self._on_close = cb

    def send(self, cmd: str):
        if not self.alive:
            raise RuntimeError("exec is closed")
        self.sock.send((cmd + "\n").encode())

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(2)
        except Exception:
            ...
        try:
            self.sock.close()
        except Exception:
            ...

    @staticmethod
    def ensure_utils_image() -> str | None:
        client: DockerClient | None = settings.DOCKER_CLIENT
        if not client:
            raise RuntimeError("No available docker client")

        image_name = settings.DOCKER_IMAGE_NAME or None
        docker_path = settings.DOCKER_IMAGE_PATH or None

        if not os.path.isdir(docker_path):
            raise RuntimeError(f"¡No existe el directorio de build! {docker_path}")

        try:
            client.images.get(image_name)
        except ImageNotFound:
            print(f"Imagen {image_name} no encontrada: construyendo...")
            client.images.build(
                path=docker_path,
                dockerfile="Dockerfile",
                tag=image_name,
                rm=True,
            )
            print(f"Imagen {image_name} construida con éxito.")
        return image_name
