from django.urls import re_path
from .consumers import ConsoleConsumer

websocket_urlpatterns = [
    re_path(r"^ws/containers/(?P<pk>\d+)/$", ConsoleConsumer.as_asgi()),
]
