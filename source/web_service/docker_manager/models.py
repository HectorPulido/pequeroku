from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Container(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="containers"
    )
    container_id = models.CharField(max_length=64, unique=True)
    image = models.CharField(max_length=128, default="ubuntu:latest")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="created")

    def __str__(self):
        return f"{self.user.username} - {self.container_id[:12]}"


class ResourceQuota(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quota",
        help_text="Cuota de recursos para este usuario",
    )
    max_containers = models.PositiveIntegerField(
        default=1, help_text="Número máximo de contenedores simultáneos"
    )
    max_memory_mb = models.PositiveIntegerField(
        default=256, help_text="Memoria máxima por contenedor en MB"
    )
    max_cpu_percent = models.PositiveIntegerField(
        default=20, help_text="CPU máxima por contenedor (como porcentaje)"
    )

    def __str__(self):
        return f"Quota {self.user.username}: {self.max_containers} \
            cont., {self.max_memory_mb}MB, {self.max_cpu_percent}% CPU"


class FileTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)

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
