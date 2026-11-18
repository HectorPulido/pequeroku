"""The isolated preview hosts only expose the preview proxy."""

from django.urls import path, re_path

from .preview_access import redeem_preview_ticket
from .urls import preview_view

urlpatterns = [
    path(
        "api/containers/<int:pk>/preview/<int:port>/.pequeroku-auth",
        redeem_preview_ticket,
    ),
    re_path(
        r"^api/containers/(?P<pk>\d+)/preview/(?P<port>\d+)(?:/(?P<path>.*))?$",
        preview_view,
        name="isolated-preview",
    ),
]
