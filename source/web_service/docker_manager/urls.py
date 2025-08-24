from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ContainersViewSet,
    LoginView,
    LogoutView,
    UserViewSet,
    FileTemplateViewSet,
)

router = DefaultRouter()
router.register(r"containers", ContainersViewSet)
router.register(r"templates", FileTemplateViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("login/", LoginView.as_view(), name="api-login"),
    path("logout/", LogoutView.as_view(), name="api-logout"),
    path("user_data/", UserViewSet.as_view(), name="user-data"),
]
