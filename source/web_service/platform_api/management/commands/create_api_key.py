"""Mint an API key for a user. The full token is printed ONCE — store it now."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from platform_api.models import APIKey


class Command(BaseCommand):
    help = "Create an API key for the public /api/v1 surface."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Owner of the key")
        parser.add_argument("--name", default="cli", help="Human label for the key")
        parser.add_argument(
            "--scopes",
            default="read,exec",
            help="Comma-separated subset of read,exec,admin (default: read,exec)",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"No user named {options['username']!r}")

        scopes = [s.strip() for s in options["scopes"].split(",") if s.strip()]
        invalid = [s for s in scopes if s not in APIKey.SCOPE_CHOICES]
        if invalid:
            raise CommandError(f"Invalid scopes: {', '.join(invalid)}")

        _obj, token = APIKey.create_key(user=user, name=options["name"], scopes=scopes)
        self.stdout.write(
            self.style.SUCCESS(
                "API key created. Store it now — it won't be shown again:"
            )
        )
        self.stdout.write(token)
