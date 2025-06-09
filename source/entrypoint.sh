#!/bin/sh
python manage.py migrate
python manage.py collectstatic --no-input
gunicorn pequeroku.wsgi:application --bind 0.0.0.0:8000  --timeout 240 --workers 3 --log-level=debug