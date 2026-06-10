from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from vm_manager.models import Container
from vm_manager.mixin import VMSyncMixin
from vm_manager import pool


class PoolManager(VMSyncMixin):
    """
    Keeps the warm pool stocked. One pass:
      1) Sync status of warm VMs so freshly-booted ones flip to 'running' (claimable).
      2) Trim surplus / now non-poolable warm VMs.
      3) Replenish each poolable type up to its pool_target, respecting node capacity.
    """

    def __init__(self, stdout, stderr) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def run_once(self) -> tuple[int, int, int]:
        """Returns (synced, trimmed, provisioned)."""
        nodes = self._candidate_nodes(heartbeat_ttl_s=3600)
        if not nodes:
            return 0, 0, 0

        node_ids = [n.pk for n in nodes]

        # 1) Sync warm VM statuses (per node, bulk) so newly booted ones become claimable.
        synced = 0
        pool_objs = list(
            Container.objects.filter(is_pool=True, node_id__in=node_ids).select_related(
                "node"
            )
        )
        if pool_objs:
            changed = self._sync_statuses(pool_objs)
            if changed:
                Container.objects.bulk_update(changed, ["status"], batch_size=200)
                synced = len(changed)

        # 2) Trim, then 3) replenish.
        trimmed = pool.trim_pools(nodes)
        provisioned = pool.replenish_pools(nodes)
        return synced, trimmed, provisioned


class Command(BaseCommand):
    help = "Keep the warm pool of pre-booted VMs stocked (see vm_manager.pool)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously, replenishing every --interval seconds.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds between passes when --loop is set (default: 30).",
        )

    def _report(self, synced: int, trimmed: int, provisioned: int) -> None:
        self.stdout.write(
            self.style.SUCCESS(
                f"[prewarm] synced={synced} trimmed={trimmed} provisioned={provisioned}"
            )
        )

    def _run_loop(self, manager: "PoolManager", interval: int) -> None:
        self.stdout.write(
            self.style.SUCCESS(f"[prewarm] loop mode started, interval={interval}s")
        )
        while True:
            close_old_connections()
            try:
                synced, trimmed, provisioned = manager.run_once()
                self._report(synced, trimmed, provisioned)
            except Exception as e:  # pylint: disable=broad-except
                self.stderr.write(self.style.ERROR(f"[prewarm] pass failed: {e}"))
            time.sleep(interval)

    def handle(self, *args, **options):
        manager = PoolManager(self.stdout, self.stderr)

        if bool(options.get("loop")):
            self._run_loop(manager, int(options.get("interval") or 30))
            return

        synced, trimmed, provisioned = manager.run_once()
        self._report(synced, trimmed, provisioned)
