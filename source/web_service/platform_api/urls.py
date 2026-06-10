"""URL config for the public ``/api/v1`` surface + its own OpenAPI schema."""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from .views import ContainerTypeViewSet, ContainerViewSet

router = DefaultRouter()
router.register("containers", ContainerViewSet, basename="v1-container")
router.register("types", ContainerTypeViewSet, basename="v1-type")

# Runs (POST /runs, GET /runs/{id}) are registered here in phase B.
try:  # pragma: no cover - additive wiring
    from .runs_views import RunViewSet

    router.register("runs", RunViewSet, basename="v1-run")
except ImportError:
    pass

api_patterns = router.urls

# Prefixed patterns used ONLY to generate the v1 schema, so paths come out as
# /api/v1/... rather than bare /containers/... .
_schema_urlconf = [path("api/v1/", include((api_patterns, "platform_api")))]

V1_SCHEMA_SETTINGS = {
    "TITLE": "PequeRoku Platform API",
    "DESCRIPTION": (
        "Infra-as-API: create and drive isolated container VMs, run code, move "
        "files, and inspect ports. Authenticate with an API key: "
        "`Authorization: Bearer pk_<prefix>_<secret>`."
    ),
    "VERSION": "1.0.0",
    # v1 schema is already scoped by urlconf; the default-schema exclusion hook
    # must NOT run here or it would strip every /api/v1 path.
    "PREPROCESSING_HOOKS": [],
}

urlpatterns = api_patterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(
            urlconf=_schema_urlconf, custom_settings=V1_SCHEMA_SETTINGS
        ),
        name="v1-schema",
    ),
    path(
        "schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="v1-schema"),
        name="v1-swagger-ui",
    ),
]
