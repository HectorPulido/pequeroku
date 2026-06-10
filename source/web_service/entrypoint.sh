#!/usr/bin/env bash
set -euo pipefail

[ -f .env ] && . ./.env || echo "No .env file, continuing..."

python manage.py migrate
python manage.py collectstatic --no-input

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "Creating super user $DJANGO_SUPERUSER_USERNAME"
  python manage.py createsuperuser --noinput || true
else
  echo "Skipping superuser creation (vars not set)"
fi

(
  sleep 5
  python manage.py reconcile_containers --loop --interval "${RECONCILE_INTERVAL:-30}"
) &

(
  sleep 5
  python manage.py prewarm_pool --loop --interval "${PREWARM_INTERVAL:-30}"
) &

(
  sleep 5
  python manage.py run_worker --loop --interval "${RUN_WORKER_INTERVAL:-5}"
) &

(
  sleep 5
  python manage.py reap_expired --loop --interval "${REAP_INTERVAL:-30}"
) &

echo "Starting gunicorn..."
DJANGO_MODULE="${DJANGO_MODULE:-pequeroku}"
exec gunicorn "${DJANGO_MODULE}.asgi:application" \
  -k uvicorn.workers.UvicornWorker \
  -w "${WORKERS:-8}" \
  -b 0.0.0.0:8000 --graceful-timeout 30 --timeout 600
