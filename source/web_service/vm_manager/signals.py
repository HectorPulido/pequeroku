from django.conf import settings
from django.db import transaction
from django.dispatch import receiver
from django.db.models.signals import post_save, post_migrate

from internal_config.models import Config
from .models import (
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
    Node,
    ContainerType,
)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_quota(sender, instance, created, **kwargs):
    """
    Create default user quota
    """
    default_values = Config.get_config_values(
        [
            "default_ai_use_per_day",
            "default_credits",
        ]
    )

    ResourceQuota.objects.get_or_create(
        user=instance,
        defaults={
            "ai_use_per_day": int(default_values.get("default_ai_use_per_day", "5")),
            "credits": int(default_values.get("default_credits", "3")),
            "active": True,
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
            "node_host": "http://vm_services:8080/",
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


@receiver(post_migrate)
def create_default_container_types(sender, **kwargs):
    """
    Seed default ContainerType instances if none exist.
    - small: 1GB RAM, 1 vCPU, 5GB disk
    - medium: 2GB RAM, 2 vCPU, 10GB disk
    - large: 4GB RAM, 4 vCPU, 25GB disk
    """
    if getattr(sender, "name", None) != "vm_manager":
        return

    if ContainerType.objects.exists():
        return

    specs = [
        {
            "container_type_name": "small",
            "memory_mb": 1024,
            "vcpus": 1,
            "disk_gib": 5,
            "credits_cost": 1,
        },
        {
            "container_type_name": "medium",
            "memory_mb": 2048,
            "vcpus": 2,
            "disk_gib": 10,
            "credits_cost": 2,
        },
        {
            "container_type_name": "large",
            "memory_mb": 4096,
            "vcpus": 4,
            "disk_gib": 25,
            "credits_cost": 4,
        },
    ]
    for s in specs:
        ContainerType.objects.create(**s)
