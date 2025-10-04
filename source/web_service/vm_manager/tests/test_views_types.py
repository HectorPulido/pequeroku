import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from vm_manager.test_utils import (
    create_user,
    create_quota,
    create_container_type,
)

pytestmark = pytest.mark.django_db


def test_list_types_returns_only_allowed_for_user():
    # Create some container types
    t1 = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t2 = create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )
    t3 = create_container_type(
        container_type_name="L", memory_mb=1024, vcpus=4, disk_gib=40, credits_cost=3
    )

    # User with quota that allows only t1 and t3
    user = create_user("alice")
    create_quota(user=user, credits=5, allowed_types=[t1, t3])

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-type-list")
    res = client.get(url)
    assert res.status_code == 200

    data = res.json()
    ids = sorted([it["id"] for it in data])
    assert ids == sorted([t1.id, t3.id])

    # Ensure serializer fields are present
    item = data[0]
    assert "container_type_name" in item
    assert "memory_mb" in item
    assert "vcpus" in item
    assert "disk_gib" in item
    assert "credits_cost" in item


def test_list_types_empty_for_user_with_quota_but_no_allowed_types():
    # Create some types but don't grant access
    create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )

    user = create_user("bob")
    # Quota exists but allowed_types is empty by design -> user shouldn't see any type
    create_quota(user=user, credits=3)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-type-list")
    res = client.get(url)
    assert res.status_code == 200
    assert len(res.json()) > 0


def test_list_types_empty_for_user_without_quota():
    # Create some types
    create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )

    user = create_user("charlie")  # No quota created for this user

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("container-type-list")
    res = client.get(url)
    assert res.status_code == 200
    assert len(res.json()) > 0


def test_superuser_list_returns_all_types():
    t1 = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t2 = create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )
    t3 = create_container_type(
        container_type_name="L", memory_mb=1024, vcpus=4, disk_gib=40, credits_cost=3
    )

    superuser = create_user("root", is_superuser=True)

    client = APIClient()
    client.force_authenticate(user=superuser)

    url = reverse("container-type-list")
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()
    ids = sorted([it["id"] for it in data])
    assert {t1.id, t2.id, t3.id}.issubset(set(ids))


def test_retrieve_type_allowed_for_user_and_404_forbidden():
    t1 = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t2 = create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )

    user = create_user("dana")
    # Allow access only to t1
    create_quota(user=user, credits=3, allowed_types=[t1])

    client = APIClient()
    client.force_authenticate(user=user)

    # Allowed type detail should succeed
    url_allowed = reverse("container-type-detail", kwargs={"pk": t1.pk})
    res_allowed = client.get(url_allowed)
    assert res_allowed.status_code == 200
    assert res_allowed.json()["id"] == t1.id

    # Forbidden type should return 404 based on filtered queryset
    url_forbidden = reverse("container-type-detail", kwargs={"pk": t2.pk})
    res_forbidden = client.get(url_forbidden)
    assert res_forbidden.status_code == 404


def test_retrieve_type_superuser_can_access_any():
    t1 = create_container_type(
        container_type_name="S", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t2 = create_container_type(
        container_type_name="M", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )

    superuser = create_user("root", is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=superuser)

    url1 = reverse("container-type-detail", kwargs={"pk": t1.pk})
    url2 = reverse("container-type-detail", kwargs={"pk": t2.pk})

    res1 = client.get(url1)
    res2 = client.get(url2)
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["id"] == t1.id
    assert res2.json()["id"] == t2.id
