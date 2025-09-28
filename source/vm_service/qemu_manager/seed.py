import os
import shutil
import subprocess

import settings

from .crypto import spec_hash


def make_overlay(base_image: str, overlay: str, disk_gib: int) -> None:
    """
    Create a qcow2 overlay disk if it doesn't already exist.

    Behavior is unchanged; still prints and no-op if overlay exists.
    """
    print("Creating the overlay with: ", base_image, overlay, disk_gib)
    if os.path.exists(overlay):
        return

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
        f"{disk_gib}G",
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
