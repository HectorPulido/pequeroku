import logging
import os

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

logger = logging.getLogger(__name__)

# Superusers get an effectively unlimited quota instead of the Config defaults.
SUPERUSER_QUOTA = 999


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_quota(sender, instance, created, **kwargs):
    """
    Create default user quota
    """
    if instance.is_superuser:
        defaults = {
            "ai_use_per_day": SUPERUSER_QUOTA,
            "credits": SUPERUSER_QUOTA,
        }
    else:
        default_values = Config.get_config_values(
            [
                "default_ai_use_per_day",
                "default_credits",
            ]
        )
        defaults = {
            "ai_use_per_day": int(default_values.get("default_ai_use_per_day", "5")),
            "credits": int(default_values.get("default_credits", "3")),
        }

    ResourceQuota.objects.get_or_create(
        user=instance,
        defaults={**defaults, "active": True},
    )


def _host_mem_mb() -> int | None:
    """Total RAM in MB seen by this container (cgroup limit or host), or None."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def _default_node_capacity() -> tuple[int, int]:
    """Capacity for the auto-created node: explicit env wins, else detect this
    host, else a sane fallback. Memory keeps ~2GB headroom for the rest of the
    stack. For a single-node local setup vm_service shares this Docker host, so
    these numbers fit; for remote nodes set NODE_CAPACITY_* or edit in admin.
    """
    env_vcpus = os.environ.get("NODE_CAPACITY_VCPUS", "").strip()
    vcpus = int(env_vcpus) if env_vcpus else (os.cpu_count() or 4)

    env_mem = os.environ.get("NODE_CAPACITY_MEM_MB", "").strip()
    if env_mem:
        mem_mb = int(env_mem)
    else:
        total = _host_mem_mb()
        mem_mb = max(total - 2048, 1024) if total else 4096
    return max(vcpus, 1), max(mem_mb, 1024)


@receiver(post_migrate)
def create_default_node(sender, **kwargs):
    """
    Create a default node sized to the host (1 vCPU / 1 GB default is unusable).
    """
    if getattr(sender, "name", None) != "vm_manager":
        return

    vcpus, mem_mb = _default_node_capacity()
    node, created = Node.objects.get_or_create(
        name="base",
        defaults={
            "node_host": "http://vm_services:8080/",
            "active": True,
            "auth_token": "N/A",
            "capacity_vcpus": vcpus,
            "capacity_mem_mb": mem_mb,
        },
    )

    if created:
        logger.info("Base node created (%s vCPU / %s MB)", vcpus, mem_mb)
    elif node.capacity_vcpus == 1 and node.capacity_mem_mb == 1024:
        # Heal a node still at the untouched model default (1 vCPU / 1 GB) — too
        # small to schedule anything. Any other capacity is left untouched.
        node.capacity_vcpus = vcpus
        node.capacity_mem_mb = mem_mb
        node.save(update_fields=["capacity_vcpus", "capacity_mem_mb"])
        logger.info("Base node capacity healed to %s vCPU / %s MB", vcpus, mem_mb)


@receiver(post_migrate)
def create_pool_user(sender, **kwargs):
    """
    Create the system user that owns warm-pool VMs (pre-booted, unclaimed).

    Kept inactive so it can never log in; its auto-created quota is harmless since
    warm VMs do not check the pool user's credits.
    """
    if getattr(sender, "name", None) != "vm_manager":
        return

    from .pool import get_pool_user

    get_pool_user()


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

    logger.info("Generating base templates")

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
            "poolable": True,
            "pool_target": 2,
        },
        {
            "container_type_name": "medium",
            "memory_mb": 2048,
            "vcpus": 2,
            "disk_gib": 10,
            "credits_cost": 2,
            "poolable": True,
            "pool_target": 2,
        },
        {
            # Heavy type stays out of the pool: never pre-built, boots on demand.
            "container_type_name": "large",
            "memory_mb": 4096,
            "vcpus": 4,
            "disk_gib": 25,
            "credits_cost": 4,
            "poolable": False,
            "pool_target": 0,
        },
    ]
    for s in specs:
        ContainerType.objects.create(**s)
