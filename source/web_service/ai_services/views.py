"""
Module to call the AI to generate the project
"""

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import exceptions
from rest_framework import status

from docker_manager.models import ResourceQuota, AIUsageLog
from .usecases.generate_code import get_project_response
from .serializers import PromptSerializer


class DailyLimitExceeded(exceptions.APIException):
    """
    Exception generated when Daily limit exceeded
    """

    status_code = 429
    default_detail = "Daily limit exceeded"
    default_code = "daily_limit_exceeded"


class AIGenerateView(APIView):
    """
    View to call the AI to generate the project
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PromptSerializer

    def post(self, request, *args, **kwargs):
        """
        Endpoint to call the AI to generate the project
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        prompt = serializer.validated_data["prompt"]

        if user is None or not user.is_authenticated:
            raise exceptions.NotAuthenticated("Not Authenticated.")

        result = None
        with transaction.atomic():
            try:
                quota = (
                    ResourceQuota.objects.select_for_update()
                    .select_related("user")
                    .get(user=user)
                )
            except ResourceQuota.DoesNotExist as e:
                raise exceptions.PermissionDenied(
                    f"The user doesn't have assigned Quota, {e}"
                )

            remaining = quota.ai_uses_left_today()
            if remaining <= 0:
                raise DailyLimitExceeded()

            generated_text = get_project_response(prompt)

            AIUsageLog.objects.create(user=user, query=prompt, response=generated_text)

            result = {
                "text": generated_text,
                "ai_uses_left_today": max(remaining - 1, 0),
            }

        return Response(result, status=status.HTTP_200_OK)
