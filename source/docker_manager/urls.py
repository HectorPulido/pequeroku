from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ContainersViewSet, LoginView, LogoutView, UserViewSet

router = DefaultRouter()
router.register(r"containers", ContainersViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("login/", LoginView.as_view(), name="api-login"),
    path("logout/", LogoutView.as_view(), name="api-logout"),
    path("user_data/", UserViewSet.as_view(), name="user-data"),
]
