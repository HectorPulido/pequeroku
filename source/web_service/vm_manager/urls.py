from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter
from .preview_proxy import (
    CSRFExemptSessionAuthentication,
    PreviewPassthroughRenderer,
    PreviewTokenAuthentication,
)
from .views import (
    ContainersViewSet,
    UserViewSet,
    FileTemplateViewSet,
    ContainerTypeViewSet,
)

router = DefaultRouter()
router.register(r"containers", ContainersViewSet, basename="container")
router.register(r"user", UserViewSet, basename="user")
router.register(r"templates", FileTemplateViewSet, basename="filetemplate")
router.register(r"container-types", ContainerTypeViewSet, basename="container-type")

# Preview proxy: a catch-all so the previewed app can use ANY path, with or
# without a trailing slash and any method. Registered outside the router (whose
# forced trailing slash would 404 a slash-less POST → APPEND_SLASH RuntimeError)
# and with CSRF disabled (the guest form carries its own token, not ours).
_preview_view = ContainersViewSet.as_view(
    {
        "get": "preview",
        "post": "preview",
        "put": "preview",
        "patch": "preview",
        "delete": "preview",
        "head": "preview",
        "options": "preview",
    },
    # Token auth (agents / browser embeds) is tried first; session auth (the IDE)
    # is the fallback. Either reaches the same preview URL.
    authentication_classes=[
        PreviewTokenAuthentication,
        CSRFExemptSessionAuthentication,
    ],
    # Wildcard renderer: a previewed app may demand any media type (e.g. Gradio's
    # SSE `Accept: text/event-stream`), which DRF's default renderers would 406.
    renderer_classes=[PreviewPassthroughRenderer],
)

urlpatterns = [
    re_path(
        r"^containers/(?P<pk>[^/]+)/preview/(?P<port>\d+)(?:/(?P<path>.*))?$",
        _preview_view,
        name="container-preview",
    ),
    path("", include(router.urls)),
]
