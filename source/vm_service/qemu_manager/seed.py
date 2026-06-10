import json
import os
import shutil
import subprocess

import settings

from .crypto import spec_hash


def _virtual_size_bytes(image: str) -> int | None:
    """Virtual size of an image in bytes, or None if it can't be read."""
    try:
        out = subprocess.run(
            ["qemu-img", "info", "--output=json", image],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(json.loads(out.stdout)["virtual-size"])
    except Exception as e:
        print("Could not read virtual size of", image, e)
        return None


def make_overlay(base_image: str, overlay: str, disk_gib: int) -> None:
    """
    Create a qcow2 overlay disk if it doesn't already exist.

    The overlay is floored to the backing image's virtual size: a qcow2 overlay
    must never be smaller than its backing image. The backing's partition table
    references blocks past a too-small overlay's end, so the root partition (and
    its PARTUUID) is truncated and the guest can't boot ("PARTUUID ... does not
    exist"). Larger is fine — the extra space stays unallocated until growpart.
    """
    print("Creating the overlay with: ", base_image, overlay, disk_gib)
    if os.path.exists(overlay):
        return

    size_bytes = int(disk_gib) * 1024**3
    backing_bytes = _virtual_size_bytes(base_image)
    if backing_bytes is not None and backing_bytes > size_bytes:
        print(
            f"Requested disk {disk_gib} GiB is smaller than the backing image "
            f"({backing_bytes / 1024**3:.0f} GiB); flooring the overlay to the "
            "backing size so the guest can boot."
        )
        size_bytes = backing_bytes

    args = [
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        "-F",
        "qcow2",
        "-b",
        base_image,
        overlay,
        str(size_bytes),
    ]
    print(args)

    try:
        _ = subprocess.run(
            args,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print("Command failed with error:", e)


def make_seed_iso(seed_iso: str, user: str, pubkey_path: str, instance_id: str) -> None:
    """
    Create (or reuse) a cloud-init seed ISO with user+root SSH access and Docker setup.

    NOTE: This intentionally preserves the original behavior, including:
      - Spec hash based on (user, pubkey contents)
      - Inline use of settings.VM_SSH_USER inside cloud-config
      - Same packages and runcmd steps (root login allowed; /app perms 0777)
    """
    print("Creating the seed iso: ", seed_iso, user, pubkey_path, instance_id)
    spec_path = seed_iso + ".spec"
    want = spec_hash(user, pubkey_path)

    if os.path.exists(seed_iso) and os.path.exists(spec_path):
        if open(spec_path, encoding="utf-8").read().strip() == want:
            print("Already exist the seed_iso")
            return

    assert os.path.exists(pubkey_path), f"No existe {pubkey_path}"
    pubkey = open(pubkey_path, encoding="utf-8").read().strip()

    user_data = f"""#cloud-config
disable_root: false
ssh_pwauth: false

users:
  - name: {settings.VM_SSH_USER}   # e.g., ubuntu if you keep using that
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo,docker
    ssh_authorized_keys:
      - {pubkey}
  - name: root
    ssh_authorized_keys:
      - {pubkey}

write_files:
  - path: /etc/ssh/sshd_config.d/pequeroku.conf
    owner: root:root
    permissions: '0644'
    content: |
      PermitRootLogin yes
      PasswordAuthentication no

"""

    meta_data = f"""instance-id: {instance_id}
local-hostname: {instance_id}
"""
    print("Writting spec")
    open(spec_path, "w", encoding="utf-8").write(want)

    wd = os.path.dirname(seed_iso)
    ud = os.path.join(wd, "user-data")
    md = os.path.join(wd, "meta-data")
    print("writting user_data")
    open(ud, "w", encoding="utf-8").write(user_data)
    print("writting metadata")
    open(md, "w", encoding="utf-8").write(meta_data)

    cloud_localds = shutil.which("cloud-localds")
    geniso = shutil.which("genisoimage") or shutil.which("mkisofs")
    if cloud_localds:
        print("Using cloud localds")
        _ = subprocess.run([cloud_localds, seed_iso, ud, md], check=True)
    else:
        print("Using geniso image")
        input_data = [
            geniso,
            "-output",
            seed_iso,
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            ud,
            md,
        ]
        # pyrefly: ignore  # no-matching-overload
        subprocess.run(input_data, check=True)
