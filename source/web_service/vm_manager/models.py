from __future__ import annotations
from collections.abc import Iterable
from typing import cast
from django.db.models import Q
from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from django.apps import apps

from django.contrib.auth.models import User

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

    arch = models.CharField(
        max_length=16, default="", help_text="Host architecture (e.g., x86_64, aarch64)"
    )
    kvm_available = models.BooleanField(
        default=False, help_text="Whether /dev/kvm is available"
    )
    capacity_vcpus = models.PositiveIntegerField(
        default=1, help_text="Total host vCPUs"
    )
    capacity_mem_mb = models.PositiveIntegerField(
        default=1024, help_text="Total host memory in MB"
    )

    healthy = models.BooleanField(
        default=False, help_text="Did the node respond correctly?"
    )
    heartbeat_at = models.DateTimeField(
        null=True, blank=True, help_text="Last heartbeat received"
    )

    def get_node_score(self) -> float:
        """
        Score a feasible node; higher is better.
        """
        running = self.get_running_containers()
        free_v, free_m = self.get_free_resources()
        return 2.0 * float(free_m) + 1.0 * float(free_v) - 0.5 * float(running)

    def get_running_containers(self) -> int:
        return int(Container.objects.filter(node=self, desired_state="running").count())

    def get_free_resources(self) -> tuple[int, int]:
        used_vcpus, used_vram = self.get_used_resources()

        free_v = max(int(self.capacity_vcpus) - used_vcpus, 0)
        free_m = max(int(self.capacity_mem_mb) - used_vram, 0)

        return free_v, free_m

    def get_used_resources(self) -> tuple[int, int]:
        vcpus = 0
        vram = 0

        containers = Container.objects.filter(node=self, desired_state="running").all()

        for container in containers:
            vcpus += int(container.vcpus)
            vram += int(container.memory_mb)

        return vcpus, vram

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
        User,
        on_delete=models.CASCADE,
        related_name="quota",
        help_text="Resource quota user",
    )
    ai_use_per_day = models.PositiveIntegerField(
        default=5, help_text="Daily request for the AI"
    )
    credits = models.PositiveIntegerField(
        default=3, help_text="Total credits available to allocate to containers"
    )
    allowed_types = models.ManyToManyField(
        "ContainerType", related_name="quotas", blank=True
    )
    active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.active:
            from django.core.management import call_command

            queryset = Container.objects.filter(resource_quota=self)
            queryset.update(desired_state="stopped")

            ids = ",".join([str(pk) for pk in queryset.values_list("pk", flat=True)])
            call_command("reconcile_containers", container_ids=ids)

        super().save(*args, **kwargs)

        # On first creation, auto-assign all non-private container types
        if is_new:
            try:
                public_type_ids = list(
                    ContainerType.objects.filter(private=False).values_list(
                        "pk", flat=True
                    )
                )
                if public_type_ids:
                    self.allowed_types.set(public_type_ids)
            except Exception:
                # Ignore errors to avoid blocking quota creation in edge cases
                pass

    def calculate_used_credits(self, user: User) -> int:
        used = 0
        qs = cast(
            Iterable[Container],
            Container.objects.filter(user=user, desired_state="running")
            .select_related("container_type")
            .all(),
        )
        for c in qs:
            if c.container_type_id and c.container_type:
                used += int(c.container_type.credits_cost)
            else:
                # Legacy containers without a type consume 1 credit by default
                used += 1
        return used

    def credits_left(self) -> int:
        user = self.user
        return max(int(self.credits) - self.calculate_used_credits(user), 0)

    def can_create_container(self, container_type: "ContainerType") -> bool:
        if not self.active:
            return False
        if not self.allowed_types.filter(pk=container_type.pk).exists():
            return False
        return self.credits_left() >= int(container_type.credits_cost)

    def ai_uses_left_today(self) -> int:
        """Get the ai uses left for today"""
        today = timezone.now().date()
        used_today = self.user.ai_usage_logs.filter(created_at__date=today).count()
        return max(self.ai_use_per_day - used_today, 0)

    def __str__(self):
        return f"Quota {self.user.username}"

    def get_user_logs(self):
        AuditLogModel = apps.get_model("internal_config", "AuditLog")

        response = []
        audit_logs = (
            AuditLogModel.objects.filter(user=self.user).order_by("-created_at").all()
        )
        for audit_log in audit_logs:
            response.append(
                (
                    audit_log.action,
                    audit_log.message,
                    audit_log.metadata,
                    audit_log.success,
                    audit_log.created_at,
                )
            )

        return response

    def get_user_ai_logs(self):
        AIUsageLogModel = apps.get_model("internal_config", "AIUsageLog")

        response = []
        audit_logs = (
            AIUsageLogModel.objects.filter(user=self.user).order_by("-created_at").all()
        )
        for audit_log in audit_logs:
            response.append(
                (
                    audit_log.query[:100],
                    audit_log.response[:100],
                    audit_log.container,
                    audit_log.created_at,
                )
            )

        return response


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


class ContainerType(models.Model):
    container_type_name = models.CharField(max_length=512)
    memory_mb = models.PositiveIntegerField(default=256, help_text="Memory in MB")
    vcpus = models.PositiveIntegerField(default=2, help_text="vCPUs")
    disk_gib = models.PositiveIntegerField(default=10, help_text="Disk size in GiB")
    credits_cost = models.PositiveIntegerField(
        default=1, help_text="Credits required to create/run this container type"
    )
    private = models.BooleanField(
        default=False,
        help_text="If true, do not auto-assign to new user quotas",
    )

    def __str__(self):
        return f"Type {self.vcpus} vCPU / {self.memory_mb} MB / {self.disk_gib} GiB (cost {self.credits_cost})"


class Container(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "created"
        PROVISIONING = "provisioning", "provisioning"
        RUNNING = "running", "running"
        STOPPED = "stopped", "stopped"
        ERROR = "error", "error"

    class DesirableStatus(models.TextChoices):
        RUNNING = "running", "running"
        STOPPED = "stopped", "stopped"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="containers")
    resource_quota = models.ForeignKey(
        "ResourceQuota",
        on_delete=models.CASCADE,
        related_name="containers",
        null=True,
        blank=True,
    )
    node = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name="container_node"
    )
    name = models.CharField(max_length=128, default="")
    container_id = models.CharField(max_length=64, unique=True)
    base_image = models.CharField(max_length=128, default="", blank=True)
    container_type = models.ForeignKey(
        "ContainerType",
        on_delete=models.SET_NULL,
        related_name="containers",
        null=True,
        blank=True,
        help_text="Selected container type; may be null for legacy containers",
    )
    first_start = models.BooleanField(default=True)
    memory_mb = models.PositiveIntegerField(
        default=256, help_text="memory for the container"
    )
    vcpus = models.PositiveIntegerField(default=2, help_text="CPU for the container")
    disk_gib = models.PositiveIntegerField(default=10, help_text="disk in gb")

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=32,
        default=Status.CREATED,
        choices=Status.choices,
        help_text="Current status",
    )

    desired_state = models.CharField(
        max_length=16,
        default=DesirableStatus.RUNNING,
        choices=DesirableStatus.choices,
        help_text="Desired state for reconciliation",
    )

    def save(self, *args, **kwargs):
        if self.user_id and hasattr(self.user, "quota"):
            self.resource_quota = self.user.quota
        if not self.name:
            self.name = get_random_name()

        # If a container type is set, ensure the resource fields reflect it
        if getattr(self, "container_type_id", None):
            ct = self.container_type
            if ct:
                self.memory_mb = int(ct.memory_mb)
                self.vcpus = int(ct.vcpus)
                self.disk_gib = int(ct.disk_gib)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    @staticmethod
    def visible_containers_for(user: User):
        return (
            Container.objects.filter(
                Q(user=user)
                | Q(
                    user__team_memberships__team__memberships__user=user,
                    user__team_memberships__active=True,
                    user__team_memberships__team__memberships__active=True,
                )
            )
            .select_related("user", "resource_quota")
            .distinct()
        )

    @staticmethod
    def can_view_container(
        user: User, container: "Container" | None = None, pk: int | None = None
    ) -> bool:
        if container:
            return (
                Container.visible_containers_for(user).filter(pk=container.pk).exists()
            )

        if pk:
            return Container.visible_containers_for(user).filter(pk=pk).exists()

        print("No container o PK provided...")
        return False

    def get_machine_logs(self):
        AuditLogModel = apps.get_model("internal_config", "AuditLog")

        response = []
        audit_logs = (
            AuditLogModel.objects.filter(
                Q(target_type="container"),
                Q(target_id=self.pk) | Q(target_id=self.container_id),
            )
            .order_by("-created_at")
            .all()
        )
        for audit_log in audit_logs:
            response.append(
                (
                    audit_log.action,
                    audit_log.message,
                    audit_log.metadata,
                    audit_log.success,
                    audit_log.created_at,
                )
            )

        return response

    def get_user_ai_logs(self):
        AIUsageLogModel = apps.get_model("internal_config", "AIUsageLog")

        response = []
        audit_logs = (
            AIUsageLogModel.objects.filter(container=self).order_by("-created_at").all()
        )
        for audit_log in audit_logs:
            response.append(
                (
                    audit_log.query[:100],
                    audit_log.response[:100],
                    audit_log.created_at,
                )
            )

        return response


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="owned_teams"
    )
    active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120]

        super().save(*args, **kwargs)

        TeamMembership.objects.update_or_create(
            user=self.owner,
            team=self,
            defaults={
                "role": TeamMembership.Role.ADMIN,
                "active": True,
            },
        )

        # If team is deactivate shut down all the memberships
        if self.active is False:
            TeamMembership.objects.filter(team=self).exclude(active=False).update(
                active=False
            )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        ADMIN = "admin", "Admin"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "team")
        indexes = [
            models.Index(fields=["user", "team"]),
            models.Index(fields=["team", "active"]),
        ]

    def __str__(self):
        return f"{self.user} in {self.team} ({self.role})"
