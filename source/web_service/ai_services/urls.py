from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AIGenerateView,
)

urlpatterns = [
    path("ai-generate/", AIGenerateView.as_view(), name="ai-generate"),
]
