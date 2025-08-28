#!/usr/bin/env bash
set -euo pipefail

# ===== FIREWALL EGRESS =====
BRIDGE4="$(ip -4 route show dev eth0 | awk '/proto kernel/ {print $1; exit}')"
BRIDGE6="$(ip -6 route show dev eth0 | awk '/proto kernel/ {print $1; exit}' || true)"

iptables -N VM_EGRESS 2>/dev/null || true
iptables -C OUTPUT -j VM_EGRESS 2>/dev/null || iptables -I OUTPUT -j VM_EGRESS
iptables -F VM_EGRESS

iptables -A VM_EGRESS -o lo -j ACCEPT
iptables -A VM_EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
if [[ -n "${BRIDGE4}" ]]; then
  iptables -A VM_EGRESS -d "${BRIDGE4}" -j ACCEPT
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
  if [[ -n "${BRIDGE6}" ]]; then
    ip6tables -A VM_EGRESS6 -d "${BRIDGE6}" -j ACCEPT
  fi
  ip6tables -A VM_EGRESS6 -d fc00::/7 -j REJECT
  ip6tables -A VM_EGRESS6 -d fe80::/10 -j REJECT
  ip6tables -A VM_EGRESS6 -j ACCEPT
fi

python manage.py migrate
python manage.py collectstatic --no-input

if [ $# -ge 1 ] && [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    --email "$DJANGO_SUPERUSER_EMAIL" || true
fi

# === Lanzar Celery worker y beat en background ===
# Opcional: espera a Redis si quieres ser más defensivo (recomendado)
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
( for i in {1..60}; do nc -z "$REDIS_HOST" "$REDIS_PORT" && exit 0; sleep 1; done; echo "Redis no responde en $REDIS_HOST:$REDIS_PORT"; exit 1 ) &

# Variables por si usas otro módulo Django
DJANGO_MODULE="${DJANGO_MODULE:-pequeroku}"

# Lanza worker
echo "Starting Celery..."
celery -A "$DJANGO_MODULE" worker --loglevel=INFO -Ofair &
PID_CELERY=$!

# Lanza beat
echo "Starting Beat..."
celery -A "$DJANGO_MODULE" beat --loglevel=INFO &
PID_BEAT=$!

# Manejo de señales: si muere uno, apagamos todo ordenadamente
terminate() {
  echo "Recibida señal, deteniendo procesos..."
  kill -TERM "$PID_CELERY" "$PID_BEAT" 2>/dev/null || true
  wait "$PID_CELERY" "$PID_BEAT" 2>/dev/null || true
}
trap terminate TERM INT

echo "Starting Daphne..."
exec daphne -b 0.0.0.0 -p 8000 "${DJANGO_MODULE}.asgi:application" 
