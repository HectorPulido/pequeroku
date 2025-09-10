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

python main.py