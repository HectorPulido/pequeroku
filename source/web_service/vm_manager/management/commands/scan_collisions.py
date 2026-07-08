"""
READ-ONLY forensic scan for the ssh_port isolation bug.

Two Container records can reach the SAME physical VM when their node-side VMRecords
end up sharing an ``ssh_port`` (see the isolation incident). This command asks every
node's vm-service for its live VMs, groups them by ``(node, ssh_port)``, and reports
any port answered by more than one VM — i.e. two container_ids that would resolve to
one machine. It also flags orphans (Container rows with no node VM) and leaks (node
VMs with no Container row).

It NEVER writes, stops, deletes, or mutates anything. Run it BEFORE deploying the
fix to size the blast radius and to know which containers must be restarted (so each
re-acquires a unique port) without losing data.

Usage:
    python manage.py scan_collisions
    python manage.py scan_collisions --json
"""

from __future__ import annotations

import json as _json
from collections import defaultdict

from django.core.management.base import BaseCommand

from vm_manager.models import Container, Node
from vm_manager.vm_client import VMServiceClient


class Command(BaseCommand):
    help = "Read-only scan for VMs sharing an ssh_port (isolation collisions)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit a machine-readable JSON report instead of text.",
        )
        parser.add_argument(
            "--all-nodes",
            action="store_true",
            help="Scan every node, not just active ones.",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        node_qs = Node.objects.all()
        if not options.get("all_nodes"):
            node_qs = node_qs.filter(active=True)
        nodes = list(node_qs)

        # container_id -> Container (one query, no per-VM DB hits)
        containers = {
            str(c.container_id): c
            for c in Container.objects.select_related("user", "node").all()
        }

        report: dict = {
            "collisions": [],
            "orphans": [],  # Container rows with no live node VM
            "leaks": [],  # node VMs with no Container row
            "node_errors": [],
        }
        seen_container_ids: set[str] = set()

        for node in nodes:
            try:
                vms = VMServiceClient(node).list_vms()
            except Exception as e:  # node down / unreachable — record and move on
                report["node_errors"].append(
                    {"node": node.name, "node_id": node.pk, "error": str(e)}
                )
                continue

            by_port: dict[int, list[dict]] = defaultdict(list)
            for vm in vms:
                vid = str(vm.get("id") or "")
                if vid:
                    seen_container_ids.add(vid)
                port = vm.get("ssh_port")
                state = str(vm.get("state") or "")
                # Only running VMs actually answer a port; a stale port on a stopped
                # record is handled by the fix, not a live collision.
                if port and state == "running":
                    by_port[int(port)].append(vm)
                if vid and vid not in containers:
                    report["leaks"].append(
                        {
                            "node": node.name,
                            "vm_id": vid,
                            "ssh_port": port,
                            "state": state,
                        }
                    )

            for port, group in by_port.items():
                if len(group) < 2:
                    continue
                members = []
                for vm in group:
                    vid = str(vm.get("id") or "")
                    c = containers.get(vid)
                    members.append(
                        {
                            "vm_id": vid,
                            "container_pk": getattr(c, "pk", None),
                            "name": getattr(c, "name", None),
                            "owner": getattr(
                                getattr(c, "user", None), "username", None
                            ),
                            "is_pool": getattr(c, "is_pool", None),
                        }
                    )
                report["collisions"].append(
                    {
                        "node": node.name,
                        "node_id": node.pk,
                        "ssh_port": port,
                        "count": len(group),
                        "members": members,
                    }
                )

        # Orphans: Container rows whose container_id was not seen on any scanned node.
        scanned_node_ids = {n.pk for n in nodes} - {
            e["node_id"] for e in report["node_errors"]
        }
        for cid, c in containers.items():
            if c.node_id in scanned_node_ids and cid not in seen_container_ids:
                report["orphans"].append(
                    {
                        "container_pk": c.pk,
                        "vm_id": cid,
                        "name": c.name,
                        "owner": getattr(c.user, "username", None),
                        "node": getattr(c.node, "name", None),
                        "status": c.status,
                    }
                )

        if as_json:
            self.stdout.write(_json.dumps(report, indent=2, default=str))
            return

        self._print_text(report)

    def _print_text(self, report: dict) -> None:
        w = self.stdout.write
        err = self.style.ERROR
        ok = self.style.SUCCESS
        warn = self.style.WARNING

        collisions = report["collisions"]
        if collisions:
            w(err(f"\n!!! {len(collisions)} PORT COLLISION(S) — two+ VMs on one port:"))
            for col in collisions:
                w(
                    err(
                        f"  node={col['node']} ssh_port={col['ssh_port']} "
                        f"count={col['count']}"
                    )
                )
                for m in col["members"]:
                    w(
                        f"      vm_id={m['vm_id']} container_pk={m['container_pk']} "
                        f"name={m['name']!r} owner={m['owner']} is_pool={m['is_pool']}"
                    )
        else:
            w(ok("\nNo live port collisions found."))

        if report["orphans"]:
            w(
                warn(
                    f"\n{len(report['orphans'])} orphan container(s) "
                    f"(row exists, no live node VM):"
                )
            )
            for o in report["orphans"]:
                w(
                    f"  pk={o['container_pk']} vm_id={o['vm_id']} name={o['name']!r} "
                    f"owner={o['owner']} status={o['status']}"
                )

        if report["leaks"]:
            w(
                warn(
                    f"\n{len(report['leaks'])} leaked node VM(s) "
                    f"(runs on node, no Container row):"
                )
            )
            for lk in report["leaks"]:
                w(f"  node={lk['node']} vm_id={lk['vm_id']} ssh_port={lk['ssh_port']}")

        if report["node_errors"]:
            w(warn(f"\n{len(report['node_errors'])} node(s) unreachable:"))
            for ne in report["node_errors"]:
                w(f"  node={ne['node']} error={ne['error']}")

        w("")  # trailing newline
