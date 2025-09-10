#!/usr/bin/env bash
set -euo pipefail

source .env

python manage.py migrate
python manage.py collectstatic --no-input

echo "Creating super user ${DJANGO_SUPERUSER_USERNAME}"
python manage.py createsuperuser --noinput || true

echo "Starting Daphne..."
DJANGO_MODULE="${DJANGO_MODULE:-pequeroku}"
exec daphne -b 0.0.0.0 -p 8000 "${DJANGO_MODULE}.asgi:application"
