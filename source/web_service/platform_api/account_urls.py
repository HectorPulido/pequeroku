"""Session-authed account routes, mounted under `/api/account/`."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .account_views import AccountAPIKeyViewSet

router = DefaultRouter()
router.register("api-keys", AccountAPIKeyViewSet, basename="account-api-key")

urlpatterns = router.urls
