"""Destroy containers whose TTL (``expires_at``) has passed.

The safety net behind ephemeral runs and ``ttl_seconds`` containers: even if a run
worker dies mid-lifecycle, the VM it booted is reaped here, so nothing orphans.
Warm-pool VMs (``expires_at`` null) are never touched.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from vm_manager.models import Container
from vm_manager.vm_client import VMServiceClient


class Command(BaseCommand):
    help = "Destroy containers past their expires_at (TTL reaper)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=int, default=30)

    def run_once(self) -> int:
        now = timezone.now()
        expired = list(
            Container.objects.filter(expires_at__lt=now).select_related("node")
        )
        reaped = 0
        for c in expired:
            try:
                VMServiceClient(c.node).delete_vm(c.container_id)
            except Exception:
                # Drop the row regardless; a leaked VM is cleaned by reconcile.
                pass
            try:
                c.delete()
                reaped += 1
            except Exception:  # pragma: no cover - defensive
                pass
        return reaped

    def handle(self, *args, **options):
        if bool(options.get("loop")):
            interval = int(options.get("interval") or 30)
            self.stdout.write(
                self.style.SUCCESS(f"[reap_expired] loop started, interval={interval}s")
            )
            while True:
                close_old_connections()
                try:
                    n = self.run_once()
                    if n:
                        self.stdout.write(
                            self.style.SUCCESS(f"[reap_expired] reaped {n}")
                        )
                except Exception as e:  # pragma: no cover - defensive
                    self.stderr.write(
                        self.style.ERROR(f"[reap_expired] pass failed: {e}")
                    )
                time.sleep(interval)
            return

        n = self.run_once()
        self.stdout.write(self.style.SUCCESS(f"[reap_expired] reaped {n}"))
