"""Serializers for the public v1 surface.

Deliberately separate from the IDE's ``vm_manager.serializers`` (which carry
session/AI fields). These expose a small, stable shape for programmatic clients.
"""

from __future__ import annotations

from rest_framework import serializers

from vm_manager.models import Container, ContainerType

from .models import Run


class ContainerSerializer(serializers.ModelSerializer):
    """Public representation of a container."""

    type = serializers.SerializerMethodField()

    class Meta:
        model = Container
        fields = [
            "id",
            "name",
            "status",
            "desired_state",
            "type",
            "vcpus",
            "memory_mb",
            "disk_gib",
            "created_at",
            "expires_at",
        ]
        read_only_fields = fields

    def get_type(self, obj: Container):
        ct = obj.container_type
        if ct is None:
            return None
        return {"id": ct.pk, "name": ct.container_type_name}


class ContainerTypeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="container_type_name")

    class Meta:
        model = ContainerType
        fields = ["id", "name", "vcpus", "memory_mb", "disk_gib", "credits_cost"]
        read_only_fields = fields


class ContainerCreateSerializer(serializers.Serializer):
    type = serializers.CharField(
        help_text="Container type id (int) or name (e.g. 'small')."
    )
    name = serializers.CharField(required=False, allow_blank=True, default="")
    ttl_seconds = serializers.IntegerField(
        required=False,
        min_value=1,
        allow_null=True,
        default=None,
        help_text="If set, the container is auto-destroyed after this many seconds.",
    )


class ContainerActionSerializer(serializers.Serializer):
    ACTIONS = ("start", "stop", "restart")
    action = serializers.ChoiceField(choices=ACTIONS)


class ExecSerializer(serializers.Serializer):
    command = serializers.CharField()
    timeout = serializers.IntegerField(
        required=False, min_value=1, max_value=600, default=None, allow_null=True
    )
    background = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, start a detached process and return a process_id.",
    )


class ProcessCreateSerializer(serializers.Serializer):
    command = serializers.CharField()


class FileItemSerializer(serializers.Serializer):
    path = serializers.CharField()
    content = serializers.CharField(
        required=False, allow_blank=True, default=None, allow_null=True
    )
    content_b64 = serializers.CharField(required=False, default=None, allow_null=True)

    def validate(self, attrs):
        if attrs.get("content") is None and attrs.get("content_b64") is None:
            raise serializers.ValidationError(
                "Each file needs either 'content' or 'content_b64'."
            )
        return attrs


class FilesUploadSerializer(serializers.Serializer):
    dest_path = serializers.CharField(required=False, default="/")
    clean = serializers.BooleanField(required=False, default=False)
    files = FileItemSerializer(many=True)


class RunCreateSerializer(serializers.Serializer):
    command = serializers.CharField()
    files = FileItemSerializer(many=True, required=False, default=list)
    type = serializers.CharField(required=False, default=None, allow_null=True)
    timeout_seconds = serializers.IntegerField(
        required=False, default=120, min_value=1, max_value=600
    )
    # The request key is "async" (a Python keyword), so the view maps it to this
    # field before validation; "is_async" is also accepted directly.
    is_async = serializers.BooleanField(required=False, default=False)


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = [
            "id",
            "status",
            "command",
            "exit_code",
            "stdout",
            "stderr",
            "truncated",
            "duration_ms",
            "error_code",
            "is_async",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields
