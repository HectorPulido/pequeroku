from rest_framework import serializers
from .models import Container, FileTemplate, FileTemplateItem


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = ["id", "container_id", "image", "created_at", "status", "user"]


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
