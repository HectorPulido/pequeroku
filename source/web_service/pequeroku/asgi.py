import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pequeroku.settings")

from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

django_asgi_app = get_asgi_application()

import pequeroku.routing as route  # noqa: E402
from pequeroku.ws_access import require_control_origin  # noqa: E402

application = ProtocolTypeRouter(
    {
        # HTTP normal (Django)
        "http": django_asgi_app,
        # WebSocket (Channels)
        "websocket": require_control_origin(
            AuthMiddlewareStack(URLRouter(route.websocket_urlpatterns))
        ),
    }
)
