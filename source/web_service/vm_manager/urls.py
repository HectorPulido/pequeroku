from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ContainersViewSet,
    UserViewSet,
    FileTemplateViewSet,
)

router = DefaultRouter()
router.register(r"containers", ContainersViewSet, basename="container")
router.register(r"user", UserViewSet, basename="user")
router.register(r"templates", FileTemplateViewSet, basename="filetemplate")

urlpatterns = [
    path("", include(router.urls)),
]
