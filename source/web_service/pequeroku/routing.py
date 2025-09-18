from django.urls import re_path
from vm_manager.consumers import ConsoleConsumer
from vm_manager.editor_consumers import EditorConsumer
from ai_services.consumers import AIConsumer

websocket_urlpatterns = [
    re_path(r"^ws/containers/(?P<pk>\d+)/$", ConsoleConsumer.as_asgi()),
    re_path(r"^ws/ai/(?P<pk>\d+)/$", AIConsumer.as_asgi()),
    re_path(r"^ws/fs/(?P<pk>\d+)/$", EditorConsumer.as_asgi()),
]
