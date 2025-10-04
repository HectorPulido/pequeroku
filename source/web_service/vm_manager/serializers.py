from rest_framework import serializers
from .models import (
    Container,
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
    ContainerType,
)


class ContainerSerializer(serializers.ModelSerializer):
    """
    Serializer for containers data
    """

    class Meta:
        """Serializer meta"""

        model = Container
        fields = [
            "id",
            "name",
            "base_image",
            "created_at",
            "status",
            "user",
            "username",
            "desired_state",
            "container_type_name",
            "memory_mb",
            "vcpus",
            "disk_gib",
        ]
        read_only_fields = [
            "id",
            "user",
            "base_image",
            "created_at",
            "status",
            "container_type_name",
            "memory_mb",
            "vcpus",
            "disk_gib",
        ]

    username = serializers.SerializerMethodField(read_only=True)
    container_type_name = serializers.SerializerMethodField(read_only=True)

    def get_username(self, obj: Container) -> str:
        """Get the username for the container"""
        return obj.user.username

    def get_container_type_name(self, obj: Container) -> str:
        if not obj.container_type:
            return "Not yet"
        return obj.container_type.container_type_name


class ContainerTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerType
        fields = [
            "id",
            "container_type_name",
            "memory_mb",
            "vcpus",
            "disk_gib",
            "credits_cost",
        ]
        read_only_fields = fields


class ResourceQuotaSerializer(serializers.ModelSerializer):
    """
    Serializer for ResourceQuota
    """

    ai_uses_left_today = serializers.SerializerMethodField()
    credits_left = serializers.SerializerMethodField()
    allowed_types = ContainerTypeSerializer(many=True, read_only=True)

    class Meta:
        """Serializer meta"""

        model = ResourceQuota
        fields = (
            "credits",
            "credits_left",
            "ai_use_per_day",
            "ai_uses_left_today",
            "active",
            "allowed_types",
        )

    def get_credits_left(self, obj) -> int:
        return obj.credits_left()

    def get_ai_uses_left_today(self, obj) -> int:
        """
        How much ai is left
        """
        return obj.ai_uses_left_today()


class UserInfoSerializer(serializers.Serializer):
    """
    Serializer for the user info
    """

    username = serializers.CharField()
    active_containers = serializers.IntegerField()
    has_quota = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    quota = serializers.SerializerMethodField()

    def get_quota(self, obj) -> dict:
        """Get the current quota for an user"""
        quota = obj.get("quota")
        if quota:
            return dict(ResourceQuotaSerializer(quota).data)
        return {
            "credits": 0,
            "ai_use_per_day": 0,
            "ai_uses_left_today": 0,
            "allowed_types": [],
        }


class FileTemplateItemSerializer(serializers.ModelSerializer):
    """
    Serializer for file template
    """

    class Meta:
        """Serializer meta"""

        model = FileTemplateItem
        fields = ["id", "path", "content", "mode", "order"]
        read_only_fields = fields


class FileTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for file template
    """

    items = FileTemplateItemSerializer(many=True, read_only=True)

    class Meta:
        """Serializer meta"""

        model = FileTemplate
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "items", "created_at", "updated_at"]


class ApplyTemplateRequestSerializer(serializers.Serializer):
    """
    Input for applying a template to a container.
    """

    container_id = serializers.IntegerField(min_value=1)
    dest_path = serializers.CharField(required=False, allow_blank=True, default="/app")
    clean = serializers.BooleanField(required=False, default=True)

    def validate_dest_path(self, value: str) -> str:
        """Ensure it starts with a slash and remove trailing slash (except root)"""

        v = (value or "/app").strip()

        if not v.startswith("/"):
            v = "/" + v
        if len(v) > 1:
            v = v.rstrip("/")

        return v


class ApplyTemplateResponseSerializer(serializers.Serializer):
    """
    Serializer for the response returned after applying a template.
    """

    status = serializers.CharField()
    template_id = serializers.IntegerField()
    container = serializers.IntegerField()
    dest_path = serializers.CharField()
    files_count = serializers.IntegerField()


class ApplyAICodeRequestSerializer(serializers.Serializer):
    """
    Input for applying AI-generated code to a container.
    """

    container_id = serializers.IntegerField(min_value=1)
    dest_path = serializers.CharField(required=False, allow_blank=True, default="/app")
    clean = serializers.BooleanField(required=False, default=False)
    content = serializers.CharField(allow_blank=False, trim_whitespace=False)

    def validate_dest_path(self, value: str) -> str:
        """Ensure it starts with a slash and remove trailing slash (except root)"""
        v = (value or "/app").strip()
        if not v.startswith("/"):
            v = "/" + v
        if len(v) > 1:
            v = v.rstrip("/")
        return v

    def validate_content(self, value: str) -> str:
        """
        Add any guardrails
        """
        if not value.strip():
            raise serializers.ValidationError("content must not be empty.")
        return value


class ApplyAICodeResponseSerializer(serializers.Serializer):
    """
    Serializer for the response returned after applying IA code.
    """

    status = serializers.CharField()
    container = serializers.IntegerField()
    dest_path = serializers.CharField()
