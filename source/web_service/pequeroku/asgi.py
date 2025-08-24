# pequeroku/asgi.py
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pequeroku.settings")

from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

# 1) Inicializa Django (carga apps, modelos, etc.)
django_asgi_app = get_asgi_application()

# 2) Ahora sí, importa rutas/consumidores que tocan modelos
import docker_manager.routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(docker_manager.routing.websocket_urlpatterns)
        ),
    }
)
