from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Container(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="containers")
    container_id = models.CharField(max_length=64, unique=True)
    image = models.CharField(max_length=128, default="ubuntu:latest")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="created")

    def __str__(self):
        return f"{self.user.username} - {self.container_id[:12]}"


class ResourceQuota(models.Model):
    user = models.OneToOneField(
        User,
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
