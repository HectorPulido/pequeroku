from django.conf import settings
from django.db import transaction
from django.dispatch import receiver
from django.db.models.signals import post_save, post_migrate

from internal_config.models import Config
from .models import ResourceQuota, FileTemplate, FileTemplateItem, Container, Node


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_quota(sender, instance, created, **kwargs):
    """
    Create default user quota
    """
    default_values = Config.get_config_values(
        [
            "default_vcpus",
            "default_mem_mib",
            "default_disk_gib",
            "max_containers",
            "default_ai_use_per_day",
        ]
    )

    ResourceQuota.objects.get_or_create(
        user=instance,
        defaults={
            "vcpus": int(default_values.get("default_vcpus", "1")),
            "max_containers": int(default_values.get("max_containers", "1")),
            "max_memory_mb": int(default_values.get("default_mem_mib", "1024")),
            "ai_use_per_day": int(default_values.get("default_ai_use_per_day", "5")),
            "default_disk_gib": int(default_values.get("default_disk_gib", "10")),
        },
    )


@receiver(post_migrate)
def create_default_node(sender, **kwargs):
    """
    Create a default node
    """
    if getattr(sender, "name", None) != "vm_manager":
        return

    _, created = Node.objects.get_or_create(
        name="base",
        defaults={
            "node_hos": "http://vm_services:8080/",
            "active": True,
            "auth_token": "N/A",
        },
    )

    print("Base node created...")


@receiver(post_migrate)
def create_default_file_templates(sender, **kwargs):
    """
    Create the default templates
    """

    default_templates: list[dict] = [
        {
            "name": "default",
            "description": "This is the simplest template ever",
            "public": True,
            "items": [
                {
                    "path": "readme.txt",
                    "content": "Simplest hello world",
                    "mode": 0o644,
                    "order": 0,
                },
                {
                    "path": "config.json",
                    "content": '{"run":"echo \'hello world\'"}',
                    "mode": 0o644,
                    "order": 1,
                },
            ],
        },
    ]

    if getattr(sender, "name", None) != "vm_manager":
        return

    print("Generating base templates...")

    with transaction.atomic():
        for tpl in default_templates:
            template, created = FileTemplate.objects.get_or_create(
                name=tpl["name"],
                defaults={
                    "description": tpl.get("description", ""),
                    "public": tpl.get("public", True),
                },
            )
            if not created:
                continue
            for i in tpl.get("items", []):
                FileTemplateItem.objects.update_or_create(
                    template=template,
                    path=i["path"],
                    defaults={
                        "content": i.get("content", ""),
                        "mode": int(i.get("mode", 0o644)),
                        "order": int(i.get("order", 0)),
                    },
                )
