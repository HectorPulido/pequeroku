"""Public API models: API keys (and ephemeral Runs, added below).

The public ``/api/v1`` surface authenticates with API keys instead of the IDE's
session cookie, so scripts and agents can drive the platform. A key is shown to
the user exactly once at creation (``pk_<prefix>_<secret>``); only its sha256 is
stored, so a leaked DB never yields usable keys.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils.crypto import constant_time_compare


def hash_secret(secret: str) -> str:
    """sha256 hex of an API key secret. Deterministic; never reversible."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class APIKey(models.Model):
    """A scoped, hashed API key owned by a user.

    Scopes form a hierarchy: ``read`` < ``exec`` < ``admin``. A key holding a
    higher scope implicitly grants the lower ones (see :meth:`has_scope`), so an
    ``admin`` key can do everything and a ``read`` key can only read.
    """

    SCOPE_READ = "read"
    SCOPE_EXEC = "exec"
    SCOPE_ADMIN = "admin"
    SCOPE_CHOICES = (SCOPE_READ, SCOPE_EXEC, SCOPE_ADMIN)
    _SCOPE_ORDER = {SCOPE_READ: 0, SCOPE_EXEC: 1, SCOPE_ADMIN: 2}

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=128, help_text="Human label for the key")
    prefix = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Public, non-secret key id used to look the key up",
    )
    hashed_key = models.CharField(
        max_length=64, help_text="sha256 of the secret; the secret is never stored"
    )
    scopes = models.JSONField(
        default=list, help_text="Subset of read/exec/admin granted to this key"
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["prefix", "revoked"])]

    def __str__(self) -> str:
        return f"APIKey {self.prefix} ({self.user.username})"

    @classmethod
    def create_key(
        cls, *, user: User, name: str, scopes: list[str] | None = None
    ) -> tuple["APIKey", str]:
        """Mint a key. Returns ``(obj, full_token)``; the token is shown once."""
        scopes = list(scopes or [cls.SCOPE_READ])
        prefix = secrets.token_hex(6)
        secret = secrets.token_hex(24)
        obj = cls.objects.create(
            user=user,
            name=name,
            prefix=prefix,
            hashed_key=hash_secret(secret),
            scopes=scopes,
        )
        return obj, f"pk_{prefix}_{secret}"

    def verify_secret(self, secret: str) -> bool:
        return constant_time_compare(hash_secret(secret), self.hashed_key)

    def has_scope(self, scope: str) -> bool:
        """True if this key grants ``scope`` (higher scopes imply lower ones)."""
        want = self._SCOPE_ORDER.get(scope)
        if want is None:
            return False
        have = max(
            (self._SCOPE_ORDER[s] for s in self.scopes if s in self._SCOPE_ORDER),
            default=-1,
        )
        return have >= want


class Run(models.Model):
    """An ephemeral one-shot: create a VM, (optionally) push files, run a command,
    collect the result, destroy the VM. Synchronous runs execute inline; async runs
    are picked up by the ``run_worker`` command and polled via ``GET /runs/{id}``.

    Credits are held implicitly: the run's container is a normal ``Container`` with
    ``desired_state=running`` and a type, so it counts in ``calculate_used_credits``
    while alive and frees on destroy — no separate billing model.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        RUNNING = "running", "running"
        SUCCEEDED = "succeeded", "succeeded"
        FAILED = "failed", "failed"
        TIMEOUT = "timeout", "timeout"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="runs")
    api_key = models.ForeignKey(
        APIKey, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    container = models.ForeignKey(
        "vm_manager.Container",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        help_text="The ephemeral VM while the run is alive; cleared after destroy.",
    )
    container_type = models.ForeignKey(
        "vm_manager.ContainerType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    command = models.TextField()
    files = models.JSONField(
        default=list,
        blank=True,
        help_text="Files to push before running (cleared after).",
    )
    timeout_seconds = models.PositiveIntegerField(default=120)
    is_async = models.BooleanField(default=False)

    status = models.CharField(
        max_length=16, default=Status.PENDING, choices=Status.choices, db_index=True
    )
    stdout = models.TextField(blank=True, default="")
    stderr = models.TextField(blank=True, default="")
    exit_code = models.IntegerField(null=True, blank=True)
    truncated = models.BooleanField(default=False)
    duration_ms = models.IntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"
