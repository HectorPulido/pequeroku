from rest_framework import serializers
from .models import Container


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = ["id", "container_id", "image", "created_at", "status", "user"]
