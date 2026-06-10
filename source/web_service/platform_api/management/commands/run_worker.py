"""Execute pending async runs (one VM lifecycle each).

Follows the project's management-command-loop pattern (like ``reconcile_containers``
and ``prewarm_pool``); no Celery. Multiple workers are safe: each run is claimed
with ``select_for_update(skip_locked=True)`` so no two workers grab the same row.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils import timezone

from platform_api import runs
from platform_api.models import Run


class Command(BaseCommand):
    help = "Execute pending async runs created via POST /api/v1/runs."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=int, default=5)

    def _claim_one(self) -> Run | None:
        with transaction.atomic():
            run = (
                Run.objects.select_for_update(skip_locked=True)
                .filter(status=Run.Status.PENDING)
                .order_by("created_at")
                .first()
            )
            if run is None:
                return None
            run.status = Run.Status.RUNNING
            run.started_at = timezone.now()
            run.save(update_fields=["status", "started_at"])
            return run

    def run_once(self) -> int:
        processed = 0
        while True:
            run = self._claim_one()
            if run is None:
                break
            try:
                runs.execute_run(run)
            except Exception as e:  # pragma: no cover - defensive
                self.stderr.write(
                    self.style.ERROR(f"[run_worker] run {run.pk} failed: {e}")
                )
            processed += 1
        return processed

    def handle(self, *args, **options):
        if bool(options.get("loop")):
            interval = int(options.get("interval") or 5)
            self.stdout.write(
                self.style.SUCCESS(f"[run_worker] loop started, interval={interval}s")
            )
            while True:
                close_old_connections()
                try:
                    n = self.run_once()
                    if n:
                        self.stdout.write(self.style.SUCCESS(f"[run_worker] ran {n}"))
                except Exception as e:  # pragma: no cover - defensive
                    self.stderr.write(
                        self.style.ERROR(f"[run_worker] pass failed: {e}")
                    )
                time.sleep(interval)
            return

        n = self.run_once()
        self.stdout.write(self.style.SUCCESS(f"[run_worker] ran {n}"))
