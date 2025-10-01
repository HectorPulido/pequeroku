from django.db import models
from django.conf import settings
from vm_manager.models import Container


class AIUsageLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_usage_logs"
    )
    container = models.ForeignKey(
        Container,
        on_delete=models.CASCADE,
        related_name="r_container",
        null=True,
        blank=True,
    )
    query = models.TextField(blank=True, default="")
    response = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    model_used = models.TextField(blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(
        default=0, help_text="Total input token used"
    )
    completion_tokens = models.PositiveIntegerField(
        default=0, help_text="Total output token used"
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]


class AIMemory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user"
    )
    container = models.ForeignKey(
        Container, on_delete=models.CASCADE, related_name="container"
    )
    memory = models.JSONField(blank=True, null=True, default=dict)


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
        ("container.delete_file", "Container delete_file"),
        ("container.change_path", "Container change_path"),
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
        ("agent_tool.read_workspace", "Agent tool read_workspace"),
        ("agent_tool.create_file", "Agent tool create_file"),
        ("agent_tool.read_file", "Agent tool read_file"),
        ("agent_tool.create_full_project", "Agent tool create_full_project"),
        ("agent_tool.exec_command", "Agent tool exec_command"),
        ("agent_tool.search", "Agent tool search"),
        ("agent_tool.search_on_internet", "Agent tool search_on_internet"),
        ("agent_tool.read_from_internet", "Agent tool read_from_internet"),
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
        created_at = f"{self.created_at:%Y-%m-%d %H:%M:%S}"
        return f"[{created_at}] {self.action} ({'ok' if self.success else 'err'})"


class Config(models.Model):
    """
    Model for Configurations flags
    """

    name = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}: {str(self.value)[:20]}"

    @staticmethod
    def get_config_value(key: str, default: str | None = None):
        """
        Get a configuration value from the database or return a default value.
        """
        value: Config | None = None
        try:
            value = Config.objects.get(name=key)
        except Config.DoesNotExist:
            return default

        if not value.value:
            return default

        return value.value

    @staticmethod
    def get_config_values(keys: list[str]) -> dict[str, str]:
        """
        Get multiple configuration values from the database.
        """
        responses: dict[str, str] = {}

        values = Config.objects.filter(name__in=keys)
        for i in values:
            responses[i.name] = i.value
        return responses
