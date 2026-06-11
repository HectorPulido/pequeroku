#!/usr/bin/env bash
set -euo pipefail

useradd --system --no-create-home --shell /usr/sbin/nologin vmnet || true

# IPv4
iptables -N VM_HOST_EGRESS 2>/dev/null || true
iptables -C OUTPUT -j VM_HOST_EGRESS 2>/dev/null || iptables -I OUTPUT -j VM_HOST_EGRESS
iptables -F VM_HOST_EGRESS

iptables -A VM_HOST_EGRESS -m owner --uid-owner vmnet -d 10.0.0.0/8 -j REJECT
iptables -A VM_HOST_EGRESS -m owner --uid-owner vmnet -d 172.16.0.0/12 -j REJECT
iptables -A VM_HOST_EGRESS -m owner --uid-owner vmnet -d 192.168.0.0/16 -j REJECT
iptables -A VM_HOST_EGRESS -m owner --uid-owner vmnet -d 169.254.0.0/16 -j REJECT

iptables -A VM_HOST_EGRESS -m owner --uid-owner vmnet -j ACCEPT

# IPv6
if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -N VM_HOST_EGRESS6 2>/dev/null || true
  ip6tables -C OUTPUT -j VM_HOST_EGRESS6 2>/dev/null || ip6tables -I OUTPUT -j VM_HOST_EGRESS6
  ip6tables -F VM_HOST_EGRESS6

  ip6tables -A VM_HOST_EGRESS6 -m owner --uid-owner vmnet -d fc00::/7 -j REJECT
  ip6tables -A VM_HOST_EGRESS6 -m owner --uid-owner vmnet -d fe80::/10 -j REJECT
  ip6tables -A VM_HOST_EGRESS6 -m owner --uid-owner vmnet -j ACCEPT
fi

if [ -e /dev/kvm ]; then
  KVM_GID="$(stat -c '%g' /dev/kvm)"
  if ! getent group "${KVM_GID}" >/dev/null; then
    if getent group kvm >/dev/null; then
      groupadd -g "${KVM_GID}" kvmhost
      KVM_GROUP=kvmhost
    else
      groupadd -g "${KVM_GID}" kvm
      KVM_GROUP=kvm
    fi
  else
    KVM_GROUP="$(getent group "${KVM_GID}" | cut -d: -f1)"
  fi
  usermod -aG "${KVM_GROUP}" vmnet
  chmod g+rw /dev/kvm
fi

# Make sure a bootable base image exists (auto-download a Debian cloud image on a
# clean machine unless VM_AUTODOWNLOAD_IMAGE=false). Never overwrites an existing one.
bash "$(dirname "$0")/scripts/ensure-base-image.sh"

# Resolve the VM SSH key. A provided key (mounted or baked at VM_SSH_PRIVKEY)
# always wins and may be of any type load_pkey supports. Only when no key is
# present do we generate an ed25519 one into the persistent vm_data volume so a
# clean machine works with zero key setup.
VM_SSH_PRIVKEY="${VM_SSH_PRIVKEY:-/root/.ssh/id_vm_pequeroku}"
if [ -f "$VM_SSH_PRIVKEY" ]; then
  echo "[vm_service] Using provided VM SSH key: $VM_SSH_PRIVKEY"
else
  GEN_KEY="/app/vm_data/keys/id_vm_pequeroku"
  if [ ! -f "$GEN_KEY" ]; then
    echo "[vm_service] No key at $VM_SSH_PRIVKEY; generating one at $GEN_KEY"
    mkdir -p "$(dirname "$GEN_KEY")"
    ssh-keygen -t ed25519 -N "" -C "pequeroku-vm" -f "$GEN_KEY"
    chmod 600 "$GEN_KEY"
  else
    echo "[vm_service] Reusing generated VM SSH key: $GEN_KEY"
  fi
  export VM_SSH_PRIVKEY="$GEN_KEY"
fi
export VM_SSH_PRIVKEY

python main.py
