import pytest

from vm_manager.models import Container
from vm_manager.test_utils import (
    create_user,
    create_quota,
    create_container_type,
    create_container,
    create_node,
)

pytestmark = pytest.mark.django_db


def test_quota_can_create_only_allowed_types_and_credits():
    user = create_user("alice")
    # Define types
    t_small = create_container_type(
        container_type_name="small", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t_large = create_container_type(
        container_type_name="large",
        memory_mb=1024,
        vcpus=2,
        disk_gib=20,
        credits_cost=2,
    )
    # Quota allows only the small type, 3 credits
    quota = create_quota(user=user, credits=3, allowed_types=[t_small])

    # Not allowed type should fail
    assert quota.can_create_container(t_large) is False
    # Allowed type within credits should pass
    assert quota.can_create_container(t_small) is True

    # After creating one small container (running), credits should be reduced by 1
    node = create_node()
    c1 = create_container(user=user, node=node, container_type=t_small)
    assert c1.desired_state == Container.DesirableStatus.RUNNING
    assert quota.credits_left() == 2
    # Still can create another small
    assert quota.can_create_container(t_small) is True


def test_quota_credits_accounting_with_running_containers_and_legacy():
    user = create_user("bob")
    t_small = create_container_type(
        container_type_name="small", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
    )
    t_medium = create_container_type(
        container_type_name="medium",
        memory_mb=512,
        vcpus=2,
        disk_gib=20,
        credits_cost=2,
    )
    quota = create_quota(user=user, credits=3, allowed_types=[t_small, t_medium])

    assert quota.credits_left() == 3

    node = create_node()
    # Create a running "small" container -> -1 credit
    c_small = create_container(user=user, node=node, container_type=t_small)
    assert quota.credits_left() == 2
    assert quota.can_create_container(t_medium) is True  # 2 >= cost(2)

    # Create a running "medium" container -> -2 credits
    c_medium = create_container(user=user, node=node, container_type=t_medium)
    assert quota.credits_left() == 0
    # No credits left for any additional container
    assert quota.can_create_container(t_small) is False

    # Stopping the medium container should free 2 credits
    c_medium.desired_state = Container.DesirableStatus.STOPPED
    c_medium.save(update_fields=["desired_state"])
    assert quota.credits_left() == 2
    assert quota.can_create_container(t_small) is True

    # Legacy container (no type) counts as 1 credit
    legacy = create_container(user=user, node=node, container_type=None)
    assert legacy.container_type is None
    assert quota.credits_left() == 1


def test_container_save_syncs_resources_from_type_on_create_and_update():
    user = create_user("charlie")
    node = create_node()

    t1 = create_container_type(
        container_type_name="t1", memory_mb=128, vcpus=1, disk_gib=8, credits_cost=1
    )
    t2 = create_container_type(
        container_type_name="t2", memory_mb=512, vcpus=2, disk_gib=20, credits_cost=2
    )

    # Create container with t1 but pass mismatching resource fields; model.save should sync to t1 values
    c = create_container(
        user=user,
        node=node,
        container_type=t1,
        memory_mb=999,
        vcpus=9,
        disk_gib=99,
        name="c-sync",
    )
    c.refresh_from_db()
    assert c.container_type_id == t1.id
    assert c.memory_mb == 128
    assert c.vcpus == 1
    assert c.disk_gib == 8

    # Change to t2 and save; resources should sync to t2 values
    c.container_type = t2
    # Put arbitrary values; save() should overwrite them based on type
    c.memory_mb = 2048
    c.vcpus = 16
    c.disk_gib = 123
    c.save()
    c.refresh_from_db()
    assert c.container_type_id == t2.id
    assert c.memory_mb == 512
    assert c.vcpus == 2
    assert c.disk_gib == 20


def test_new_quota_auto_assigns_public_container_types():
    # Create public and private types BEFORE creating the user/quota
    t_public1 = create_container_type(
        container_type_name="pub1", memory_mb=256, vcpus=1, disk_gib=5, credits_cost=1
    )
    t_public2 = create_container_type(
        container_type_name="pub2", memory_mb=512, vcpus=2, disk_gib=10, credits_cost=1
    )
    t_private = create_container_type(
        container_type_name="priv", memory_mb=1024, vcpus=2, disk_gib=20, credits_cost=2
    )
    # Mark one as private
    t_private.private = True
    t_private.save()

    # Now create user so the quota (created by signal) captures all public types
    user = create_user("auto_public")
    quota = create_quota(user=user, credits=5)

    # Auto-assignment should include all non-private types present at creation time
    assigned_ids = sorted([ct.id for ct in quota.allowed_types.all()])
    expected_ids = sorted(
        list(
            t_public1.__class__.objects.filter(private=False).values_list(
                "id", flat=True
            )
        )
    )
    assert assigned_ids == expected_ids
