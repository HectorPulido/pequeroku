from rest_framework import serializers


class PromptSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=4000, allow_blank=False, trim_whitespace=True
    )
