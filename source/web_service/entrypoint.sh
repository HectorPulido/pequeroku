#!/bin/sh
set -e

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