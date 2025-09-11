from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone

from namesgenerator import get_random_name


class Node(models.Model):
    name = models.CharField(
        max_length=128,
    )
    node_host = models.CharField(
        max_length=128,
    )
    active = models.BooleanField(default=True)
    auth_token = models.CharField(max_length=128, default="")

    @staticmethod
    def get_node_by_name(name: str) -> "Node|None":
        return Node.objects.filter(name=name).last()

    @staticmethod
    def get_random_node() -> "Node|None":
        return Node.objects.order_by("?").last()

    def __str__(self):
        return f"Node {self.name}"


class ResourceQuota(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quota",
        help_text="Resource quota user",
    )
    max_containers = models.PositiveIntegerField(
        default=1, help_text="Max number of alive containers"
    )
    max_memory_mb = models.PositiveIntegerField(
        default=256, help_text="Max memory per container MB"
    )
    vcpus = models.PositiveIntegerField(
        default=2, help_text="Max CPU per container VCPU"
    )
    ai_use_per_day = models.PositiveIntegerField(
        default=5, help_text="Daily request for the AI"
    )
    default_disk_gib = models.PositiveIntegerField(
        default=10, help_text="Max disk in gb"
    )

    def can_create_container(self, user) -> bool:
        active = Container.objects.filter(user=user).count()
        return self.max_containers > active

    def ai_uses_left_today(self) -> int:
        """Get the ai uses left for today"""
        today = timezone.now().date()
        used_today = self.user.ai_usage_logs.filter(created_at__date=today).count()
        return max(self.ai_use_per_day - used_today, 0)

    def __str__(self):
        return f"Quota {self.user.username}"


class FileTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    public = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Template: {self.name} ({self.pk})"

    @property
    def items_count(self):
        return self.items.count()


class FileTemplateItem(models.Model):
    template = models.ForeignKey(
        FileTemplate, on_delete=models.CASCADE, related_name="items"
    )
    path = models.CharField(max_length=512)
    content = models.TextField(blank=True, default="")
    mode = models.PositiveIntegerField(default=0o644)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("template", "path"),)
        ordering = ("order", "path")

    def __str__(self):
        return f"{self.template.name}:{self.path}"


class Container(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="containers"
    )
    node = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name="container_node"
    )
    name = models.CharField(max_length=128, default="")
    container_id = models.CharField(max_length=64, unique=True)
    base_image = models.CharField(max_length=128, default="", blank=True)
    first_start = models.BooleanField(default=True)
    memory_mb = models.PositiveIntegerField(
        default=256, help_text="memory for the container"
    )
    vcpus = models.PositiveIntegerField(default=2, help_text="CPU for the container")
    disk_gib = models.PositiveIntegerField(default=10, help_text="disk in gb")

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="created")

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = get_random_name()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.name}"
