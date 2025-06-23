import os
import threading

from django.conf import settings
from docker import DockerClient
from docker.errors import ImageNotFound

from .models import Container


class DockerSession:
    def __init__(self, container_obj: Container, docker_client: DockerClient):
        res = docker_client.api.exec_create(
            container_obj.container_id, cmd=["/bin/bash"], stdin=True, tty=True
        )
        self.exec_id = res["Id"]
        sock = docker_client.api.exec_start(
            self.exec_id, tty=True, detach=False, socket=True
        )
        self.sock = sock._sock
        self.key = f"logs:{container_obj.pk}"

        def reader():
            while True:
                try:
                    data = self.sock.recv(4096)
                    if not data:
                        break
                    # dividimos en líneas y las guardamos
                    text = data.decode("utf-8", errors="ignore")
                    for line in text.splitlines():
                        settings.REDIS_CLIENT.rpush(self.key, line)
                        settings.REDIS_CLIENT.ltrim(self.key, -1000, -1)
                except Exception:
                    break

        t = threading.Thread(target=reader, daemon=True)
        t.start()

    @staticmethod
    def ensure_utils_image() -> str:
        """
        Comprueba si existe la imagen settings.DOCKER_IMAGE_NAME;
        si no, la construye desde settings.DOCKER_IMAGE_PATH y la etiqueta.
        Devuelve el tag listo para usar en .run().
        """
        client: DockerClient = settings.DOCKER_CLIENT
        image_name = settings.DOCKER_IMAGE_NAME
        docker_path = settings.DOCKER_IMAGE_PATH

        if not os.path.isdir(docker_path):
            raise RuntimeError(f"¡No existe el directorio de build! {docker_path}")

        try:
            client.images.get(image_name)
        except ImageNotFound:
            print(f"Imagen {image_name} no encontrada: construyendo...")
            # build() devuelve un tupla (image, logs), aquí podemos ignorar logs
            client.images.build(
                path=docker_path,
                dockerfile="Dockerfile",
                tag=image_name,
                rm=True,  # limpia contenedores intermedios
            )
            print(f"Imagen {image_name} construida con éxito.")
        return image_name

    def send(self, cmd: str):
        self.sock.send((cmd + "\n").encode())
