import os
import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from vm_manager import routing as vm_manager_routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pequeroku.settings")
django.setup()

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        # HTTP normal (Django)
        "http": django_asgi_app,
        # WebSocket (Channels)
        "websocket": AuthMiddlewareStack(
            URLRouter(vm_manager_routing.websocket_urlpatterns)
        ),
    }
)
