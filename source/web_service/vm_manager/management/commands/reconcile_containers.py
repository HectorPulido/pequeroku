from __future__ import annotations

from typing import Iterable, List, Tuple
from django.core.management.base import BaseCommand

from vm_manager.models import Container, Node
from vm_manager.vm_client import VMServiceClient, VMAction
from vm_manager.mixin import VMSyncMixin

from internal_config.models import AuditLog


class Reconciler(VMSyncMixin):
    """
    Single-pass reconciler enforcing desired_state for containers.

    Steps per batch:
      1) Sync real 'status' from vm-service (bulk)
      2) For each container:
           - If desired_state == 'running' and status in (stopped, error) -> start
           - If desired_state == 'stopped' and status == 'running' -> stop
      3) Persist any status hints set locally (e.g., provisioning after start)
    """

    def __init__(self, stdout, stderr) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def _service_for(self, c: Container) -> VMServiceClient | None:
        try:
            node: Node = c.node  # type: ignore
        except Node.DoesNotExist:
            return None
        if not node or not node.active:
            return None
        return VMServiceClient(node)

    def _audit(
        self, action: str, c: Container, message: str, success: bool, metadata=None
    ):
        try:
            AuditLog.objects.create(
                user=c.user if hasattr(c, "user_id") else None,
                action=action,
                target_type="container",
                target_id=str(c.pk),
                message=message,
                metadata=metadata or {},
                ip=None,
                user_agent="reconciler/cron",
                success=success,
            )
        except Exception:
            pass

    def _iter_batches(self, batch_size: int = 200) -> Iterable[List[Container]]:
        qs = Container.objects.select_related("node", "user").all().order_by("pk")
        batch: List[Container] = []
        for obj in qs.iterator(chunk_size=batch_size):
            batch.append(obj)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def reconcile_batch(self, objs: List[Container]) -> Tuple[int, int]:
        """
        Reconcile a group of containers. Returns (actions_sent, updated_rows)
        """
        actions = 0
        updated: List[Container] = []

        # 1) Sync statuses with vm-service in bulk (per node)
        changed = self._sync_statuses(objs)
        if changed:
            # Persist status updates fetched from vm-service
            Container.objects.bulk_update(changed, ["status"], batch_size=200)

        # 2) Enforce desired state
        for c in objs:
            if not c.container_id or not c.node_id:
                continue

            desired = (c.desired_state or "running").strip()
            status = (c.status or "").strip()

            # Already desired
            if (desired == "running" and status == "running") or (
                desired == "stopped" and status == "stopped"
            ):
                continue

            client = self._service_for(c)
            if not client:
                continue

            try:
                if desired == "running" and status in (
                    "stopped",
                    "error",
                    "created",
                    "creating",
                ):
                    client.action_vm(
                        str(c.container_id),
                        VMAction(action="start", cleanup_disks=False),
                    )
                    actions += 1
                    # Hint locally; the next sync will set real state
                    c.status = "provisioning"
                    updated.append(c)
                    self._audit(
                        "container.power_on",
                        c,
                        "Reconciler requested power on",
                        True,
                        {"container_id": c.container_id},
                    )
                elif desired == "stopped" and status == "running":
                    client.action_vm(
                        str(c.container_id),
                        VMAction(action="stop", cleanup_disks=False),
                    )
                    actions += 1
                    # We can optimistically mark as stopping; next sync will confirm
                    c.status = "stopped"
                    updated.append(c)
                    self._audit(
                        "container.power_off",
                        c,
                        "Reconciler requested power off",
                        True,
                        {"container_id": c.container_id},
                    )
            except Exception as e:
                self._audit(
                    "container.real_status",
                    c,
                    f"Action error during reconciliation: {e}",
                    False,
                    {
                        "container_id": c.container_id,
                        "desired": desired,
                        "status": status,
                    },
                )
                # Keep going with other containers

        # 3) Persist local hints
        if updated:
            try:
                Container.objects.bulk_update(updated, ["status"], batch_size=200)
            except Exception:
                # Best effort; continue
                pass

        return actions, len(updated)

    def reconcile_once(self) -> Tuple[int, int, int]:
        """
        Run one full pass over all containers.

        Returns tuple: (batches, actions_sent, rows_updated)
        """
        batches = 0
        actions_total = 0
        updated_total = 0

        for batch in self._iter_batches():
            batches += 1
            actions, updates = self.reconcile_batch(batch)
            actions_total += actions
            updated_total += updates

        return batches, actions_total, updated_total


class Command(BaseCommand):
    help = "Reconcile containers' desired state with actual state by talking to vm-service."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only compute and print plan; do not send actions or update DB.",
        )
        parser.add_argument(
            "--container-ids",
            dest="container_ids",
            help="Only reconcile the specified container_id",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        container_ids = []
        try:
            container_ids = options.get("container_ids", "").split(",")
        except:
            ...

        reconciler = Reconciler(self.stdout, self.stderr)

        if dry_run:
            # For simplicity, just run normal pass but do not send actions nor persist hints
            # We simulate by monkey-patching methods; kept minimal to avoid complexity.
            orig_sync = reconciler._sync_statuses
            _ = reconciler.reconcile_batch

            def _dry_sync(objs: List[Container]):
                # Still sync from vm-service to show what would change
                return orig_sync(objs)

            def _dry_reconcile(objs: List[Container]):
                # Compute but avoid calling vm-service; do not persist local hints
                actions = 0
                _ = reconciler._sync_statuses(objs)
                # no DB write here
                for c in objs:
                    desired = (c.desired_state or "running").strip()
                    status = (c.status or "").strip()
                    if desired == "running" and status in (
                        "stopped",
                        "error",
                        "created",
                        "creating",
                    ):
                        actions += 1
                    elif desired == "stopped" and status == "running":
                        actions += 1
                return actions, 0

            reconciler._sync_statuses = _dry_sync  # type: ignore
            reconciler.reconcile_batch = _dry_reconcile  # type: ignore

        if len(container_ids) > 0:
            try:
                obj = Container.objects.select_related("node", "user").get(
                    pk__in=container_ids
                )
            except Container.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(
                        f"[reconciler] container {container_ids} not found"
                    )
                )
                return
            actions_total, updated_total = reconciler.reconcile_batch([obj])
            batches = 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"[reconciler] container_id={container_ids} batches={batches} actions={actions_total} local_updates={updated_total}"
                )
            )
            return

        batches, actions_total, updated_total = reconciler.reconcile_once()

        self.stdout.write(
            self.style.SUCCESS(
                f"[reconciler] batches={batches} actions={actions_total} local_updates={updated_total}"
            )
        )
