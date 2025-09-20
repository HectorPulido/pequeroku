# conftest.py
import os
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pequeroku.settings_test")


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture(autouse=True)
def _configure_test_settings(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }
