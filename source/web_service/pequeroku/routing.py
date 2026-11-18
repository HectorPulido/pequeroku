from django.urls import re_path
from vm_manager.console_consumers import ConsoleConsumer
from vm_manager.editor_consumers import EditorConsumer
from ai_services.ai_consumers import AIConsumer
from pequeroku.ws_access import require_live_container_access

websocket_urlpatterns = [
    re_path(
        r"^ws/containers/(?P<pk>\d+)/$",
        require_live_container_access(ConsoleConsumer.as_asgi()),
    ),
    re_path(
        r"^ws/ai/(?P<pk>\d+)/$", require_live_container_access(AIConsumer.as_asgi())
    ),
    re_path(
        r"^ws/fs/(?P<pk>\d+)/$", require_live_container_access(EditorConsumer.as_asgi())
    ),
]
