import pytest
from django.contrib.auth import get_user_model

from vm_manager.signals import SUPERUSER_QUOTA

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_superuser_quota_is_unlimited():
    user = User.objects.create_superuser(username="root", password="pass1234", email="")
    assert user.quota.credits == SUPERUSER_QUOTA
    assert user.quota.ai_use_per_day == SUPERUSER_QUOTA


def test_regular_user_quota_uses_config_defaults():
    user = User.objects.create_user(username="bob", password="pass1234")
    assert user.quota.credits == 3
    assert user.quota.ai_use_per_day == 5
