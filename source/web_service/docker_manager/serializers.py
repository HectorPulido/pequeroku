from rest_framework import serializers
from .models import Container, FileTemplate, FileTemplateItem


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = [
            "id",
            "container_id",
            "image",
            "created_at",
            "status",
            "user",
            "username",
        ]

    username = serializers.SerializerMethodField("get_username")

    def get_username(self, obj) -> str:
        return obj.user.username


class FileTemplateItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileTemplateItem
        fields = ["id", "path", "content", "mode", "order"]
        read_only_fields = fields


class FileTemplateSerializer(serializers.ModelSerializer):
    items = FileTemplateItemSerializer(many=True, read_only=True)

    class Meta:
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
