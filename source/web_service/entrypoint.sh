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

echo "Starting Daphne..."
DJANGO_MODULE="${DJANGO_MODULE:-pequeroku}"
exec daphne -b 0.0.0.0 -p 8000 "${DJANGO_MODULE}.asgi:application"
