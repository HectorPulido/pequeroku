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


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("login", "Login"),
        ("logout", "Logout"),
        ("container.create", "Container create"),
        ("container.destroy", "Container destroy"),
        ("container.power_on", "Container power_on"),
        ("container.power_off", "Container power_off"),
        ("container.restart_shell", "Container restart_shell"),
        ("container.send_command", "Container send_command"),
        ("container.read_file", "Container read_file"),
        ("container.write_file", "Container write_file"),
        ("container.upload_file", "Container upload_file"),
        ("container.list_dir", "Container list_dir"),
        ("container.create_dir", "Container create_dir"),
        ("container.real_status", "Container real_status"),
        ("template.apply", "Template apply"),
        ("user.info", "User Info"),
        ("ws.connect", "WS Connect"),
        ("ws.disconnect", "WS Disconnect"),
        ("ws.restart", "WS Restart"),
        ("ws.cmd", "WS Cmd"),
        ("ws.ctrlc", "WS Ctrlc"),
        ("ws.ctrld", "WS Ctrld"),
        ("ws.clear", "WS Clear"),
        ("ws.unknown", "WS Unknown"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=64, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    message = models.TextField(blank=True, default="")
    metadata = models.JSONField(blank=True, null=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    success = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {self.action} ({'ok' if self.success else 'err'})"
