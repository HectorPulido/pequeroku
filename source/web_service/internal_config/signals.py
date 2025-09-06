from django.db.models.signals import post_migrate
from django.dispatch import receiver
from .models import Config


@receiver(post_migrate)
def create_default_configs(sender, **kwargs):
    """
    Create default configs
    """
    if getattr(sender, "name", None) != "internal_config":
        return

    print("Generating base configs...")

    defaults = [
        {"name": "default_ai_use_per_day", "value": "5", "description": ""},
        {"name": "max_containers", "value": "2", "description": ""},
        {"name": "default_disk_gib", "value": "10", "description": ""},
        {"name": "default_mem_mib", "value": "2048", "description": ""},
        {"name": "default_vcpus", "value": "2", "description": ""},
        {"name": "openai_model", "value": "openai/gpt-oss-120b", "description": ""},
        {
            "name": "openai_api_url",
            "value": "https://api.groq.com/openai/v1",
            "description": "",
        },
        {"name": "openai_api_key", "value": "gsk_...", "description": ""},
    ]
    for item in defaults:
        Config.objects.get_or_create(name=item["name"], defaults=item)
