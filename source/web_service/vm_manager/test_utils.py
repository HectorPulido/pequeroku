from django.utils import timezone
from django.contrib.auth import get_user_model
from vm_manager.models import (
    Node,
    Container,
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
    ContainerType,
)
from vm_manager.serializers import (
    ContainerSerializer,
    ResourceQuotaSerializer,
    UserInfoSerializer,
    FileTemplateSerializer,
    ApplyTemplateRequestSerializer,
    ApplyTemplateResponseSerializer,
    ApplyAICodeRequestSerializer,
    ApplyAICodeResponseSerializer,
)


User = get_user_model()


def create_user(username="alice", password="pass1234", is_superuser=False):
    return User.objects.create_user(
        username=username, password=password, is_superuser=is_superuser
    )


def create_quota(user=None, **kwargs):
    if user is None:
        user = create_user()
    # Drop legacy kwargs that no longer exist on the model
    legacy_keys = ["max_containers", "max_memory_mb", "vcpus", "default_disk_gib"]
    for k in legacy_keys:
        kwargs.pop(k, None)
    # Accept optional allowed_types to assign M2M after creation
    allowed_types = kwargs.pop("allowed_types", None)

    defaults = dict(
        ai_use_per_day=5,
        credits=3,
        active=True,
    )
    defaults.update(kwargs)

    obj, _ = ResourceQuota.objects.update_or_create(user=user, defaults=defaults)

    # Assign allowed container types if provided
    if allowed_types is not None:
        ids = []
        for t in allowed_types:
            if isinstance(t, int):
                ids.append(t)
            else:
                try:
                    ids.append(t.pk)
                except AttributeError:
                    continue
        obj.allowed_types.set(ids)

    # Bust OneToOne cached relation to ensure fresh DB read in tests
    if hasattr(user, "__dict__") and "quota" in user.__dict__:
        user.__dict__.pop("quota", None)

    return obj


def create_container_type(
    container_type_name="default", memory_mb=256, vcpus=1, disk_gib=10, credits_cost=1
):
    return ContainerType.objects.create(
        container_type_name=container_type_name,
        memory_mb=memory_mb,
        vcpus=vcpus,
        disk_gib=disk_gib,
        credits_cost=credits_cost,
    )


def create_node(
    name="node-1",
    host="http://127.0.0.1:8080",
    healthy=True,
    heartbeat=True,
    capacity_vcpus=4,
    capacity_mem_mb=4096,
):
    node = Node.objects.create(
        name=name,
        node_host=host,
        active=True,
        healthy=healthy,
        capacity_vcpus=capacity_vcpus,
        capacity_mem_mb=capacity_mem_mb,
        auth_token="",
    )
    if heartbeat:
        node.heartbeat_at = timezone.now()
        node.save(update_fields=["heartbeat_at"])
    return node


def create_container(
    user=None,
    node=None,
    with_quota=True,
    container_id=None,
    container_type=None,
    **kwargs,
):
    if user is None:
        user = create_user()
    if node is None:
        node = create_node()
    if with_quota and not hasattr(user, "quota"):
        create_quota(user=user)
    if container_id is None:
        container_id = f"vm-{int(timezone.now().timestamp()*1_000_000_000)}"
    defaults = dict(
        name="my-container",
        base_image="",
        memory_mb=512,
        vcpus=2,
        disk_gib=10,
        status=Container.Status.RUNNING,
        desired_state=Container.DesirableStatus.RUNNING,
    )
    if container_type is not None:
        defaults["container_type"] = container_type
    defaults.update(kwargs)
    return Container.objects.create(
        user=user,
        node=node,
        container_id=container_id,
        **defaults,
    )
