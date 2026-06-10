"""``/api/v1/runs`` — ephemeral one-shot runs (sync + async).

``POST /runs`` with ``async=false`` runs inline and returns the result.
``POST /runs`` with ``async=true`` returns ``202 {id, status}`` (the run id is the
handle to poll) and the ``run_worker`` command executes it.
``GET /runs/{id}`` returns status + result.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from vm_manager import orchestration
from vm_manager.models import ContainerType

from . import idempotency, runs
from .errors import APIError
from .models import APIKey, Run
from .serializers import RunCreateSerializer, RunSerializer
from .views import PlatformViewSet


class RunViewSet(PlatformViewSet):
    def required_scope(self) -> str:
        return APIKey.SCOPE_EXEC if self.action == "create" else APIKey.SCOPE_READ

    def _resolve_type(self, quota, value) -> ContainerType:
        if value is None:
            # Default to the cheapest type the user is allowed to use.
            ct = quota.allowed_types.order_by("credits_cost").first()
            if ct is None:
                raise APIError(
                    "type_not_allowed", "Your quota has no allowed container types"
                )
            return ct
        try:
            return ContainerType.objects.get(pk=int(value))
        except (ValueError, TypeError, ContainerType.DoesNotExist):
            pass
        ct = quota.allowed_types.filter(container_type_name=str(value)).first()
        if ct is None:
            ct = ContainerType.objects.filter(container_type_name=str(value)).first()
        if ct is None:
            raise APIError("invalid_request", f"Unknown container type '{value}'")
        return ct

    def create(self, request):
        cache_key, cached = idempotency.lookup(request, "runs")
        if cached is not None:
            return Response(cached["data"], status=cached["status"])

        # 'async' is a reserved word and can't be a serializer field attribute;
        # normalize it into 'is_async' before validation.
        data = dict(request.data)
        if "async" in data and "is_async" not in data:
            data["is_async"] = data.pop("async")

        ser = RunCreateSerializer(data=data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        quota = orchestration.check_quota(request.user)
        if quota is None:
            raise APIError("quota_exceeded", "No active quota assigned to this user")

        ct = self._resolve_type(quota, d.get("type"))
        if not quota.allowed_types.filter(pk=ct.pk).exists():
            raise APIError(
                "type_not_allowed", "This container type is not allowed for your quota"
            )
        if not quota.can_create_container(container_type=ct):
            raise APIError("quota_exceeded", "Not enough credits to start this run")

        run = Run.objects.create(
            user=request.user,
            api_key=request.auth if hasattr(request.auth, "pk") else None,
            container_type=ct,
            command=d["command"],
            files=d.get("files") or [],
            timeout_seconds=d["timeout_seconds"],
            is_async=d["is_async"],
        )

        if run.is_async:
            out = RunSerializer(run).data
            idempotency.store(cache_key, status.HTTP_202_ACCEPTED, out)
            return Response(out, status=status.HTTP_202_ACCEPTED)

        runs.execute_run(run)
        out = RunSerializer(run).data
        idempotency.store(cache_key, status.HTTP_200_OK, out)
        return Response(out, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        try:
            run = Run.objects.get(pk=pk, user=request.user)
        except (Run.DoesNotExist, ValueError, TypeError):
            raise APIError("not_found", "Run not found")
        return Response(RunSerializer(run).data)
