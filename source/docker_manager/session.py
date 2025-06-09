import threading

from django.conf import settings
from docker import DockerClient

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

    def send(self, cmd: str):
        self.sock.send((cmd + "\n").encode())
