from django.urls import path
from .views import (
    AIGenerateView,
)

urlpatterns = [
    path("ai-generate/", AIGenerateView.as_view(), name="ai-generate"),
]
