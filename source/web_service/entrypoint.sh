#!/bin/sh
set -euo pipefail

BRIDGE_SUBNET="$(ip -4 route show dev eth0 | awk '/proto kernel/{print $1; exit}')"
DOCKER_DNS="127.0.0.11"

iptables -N VM_EGRESS 2>/dev/null || true
iptables -C OUTPUT -j VM_EGRESS 2>/dev/null || iptables -I OUTPUT -j VM_EGRESS

iptables -F VM_EGRESS

iptables -A VM_EGRESS -o lo -j ACCEPT
iptables -A VM_EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A VM_EGRESS -d "${DOCKER_DNS}" -p udp --dport 53 -j ACCEPT
iptables -A VM_EGRESS -d "${DOCKER_DNS}" -p tcp --dport 53 -j ACCEPT
if [[ -n "${BRIDGE_SUBNET}" ]]; then
  iptables -A VM_EGRESS -d "${BRIDGE_SUBNET}" -j ACCEPT
fi

iptables -A VM_EGRESS -d 10.0.0.0/8 -j REJECT
iptables -A VM_EGRESS -d 172.16.0.0/12 -j REJECT
iptables -A VM_EGRESS -d 192.168.0.0/16 -j REJECT
iptables -A VM_EGRESS -d 169.254.0.0/16 -j REJECT

iptables -A VM_EGRESS -j ACCEPT

if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -N VM_EGRESS6 2>/dev/null || true
  ip6tables -C OUTPUT -j VM_EGRESS6 2>/dev/null || ip6tables -I OUTPUT -j VM_EGRESS6
  ip6tables -F VM_EGRESS6

  ip6tables -A VM_EGRESS6 -o lo -j ACCEPT
  ip6tables -A VM_EGRESS6 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  BRIDGE_SUBNET6="$(ip -6 route show dev eth0 | awk '/proto kernel/{print $1; exit}')"
  if [[ -n "${BRIDGE_SUBNET6:-}" ]]; then
    ip6tables -A VM_EGRESS6 -d "${BRIDGE_SUBNET6}" -j ACCEPT
  fi

  ip6tables -A VM_EGRESS6 -d fc00::/7 -j REJECT
  ip6tables -A VM_EGRESS6 -d fe80::/10 -j REJECT

  ip6tables -A VM_EGRESS6 -j ACCEPT
fi

python manage.py migrate
python manage.py collectstatic --no-input

if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    --email "$DJANGO_SUPERUSER_EMAIL" || true
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
else
  # ASGI server para websockets
  exec daphne -b 0.0.0.0 -p 8000 pequeroku.asgi:application
fi