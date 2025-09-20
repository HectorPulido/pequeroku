import pytest

from vm_manager.models import (
    Node,
    Container,
    ResourceQuota,
    FileTemplate,
    FileTemplateItem,
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

from vm_manager.test_utils import (
    create_quota,
    create_user,
    create_node,
    create_container,
)

pytestmark = pytest.mark.django_db


def test_container_serializer_serializes_username_and_basic_fields():
    user = create_user(username="bob")
    node = create_node()
    c = create_container(user=user, node=node, container_id="vm-001")

    ser = ContainerSerializer(instance=c)
    data = ser.data

    assert data["id"] == c.id
    assert data["name"] == "my-container"
    assert data["container_id"] == "vm-001"
    assert data["status"] == Container.Status.RUNNING
    assert data["desired_state"] == Container.DesirableStatus.RUNNING
    assert data["memory_mb"] == 512
    assert data["vcpus"] == 2
    assert data["disk_gib"] == 10
    # SerializerMethodField
    assert data["username"] == "bob"


def test_container_serializer_read_only_fields_are_ignored_on_update():
    user = create_user(username="carol")
    c = create_container(user=user, container_id="vm-xyz", memory_mb=256, vcpus=1)

    # Attempt to change read-only fields
    ser = ContainerSerializer(
        instance=c,
        data={
            "memory_mb": 2048,  # read-only
            "vcpus": 8,  # read-only
            "disk_gib": 999,  # read-only
            "name": "updated-name",  # writable
        },
        partial=True,
    )
    assert ser.is_valid(), ser.errors
    obj = ser.save()

    obj.refresh_from_db()
    # Read-only fields did not change
    assert obj.memory_mb == 256
    assert obj.vcpus == 1
    assert obj.disk_gib == 10
    # Writable field changed
    assert obj.name == "updated-name"


def test_resource_quota_serializer_ai_uses_left_today_equals_total_when_unused():
    user = create_user(username="dave")
    quota = create_quota(user=user, ai_use_per_day=7)

    ser = ResourceQuotaSerializer(instance=quota)
    data = ser.data

    assert data["ai_use_per_day"] == 7
    # No AIUsageLog entries yet, so left == total
    assert data["ai_uses_left_today"] == 7
    assert data["active"] is True


def test_user_info_serializer_without_quota_returns_defaults():
    user = create_user(username="erin")
    # No quota on purpose
    payload = {
        "username": user.username,
        "is_superuser": user.is_superuser,
        "active_containers": 0,
        "has_quota": False,
        "quota": None,
    }
    ser = UserInfoSerializer(instance=payload)
    data = ser.data

    assert data["username"] == "erin"
    assert data["has_quota"] is False
    assert data["quota"]["max_containers"] == 0
    assert data["quota"]["max_memory_mb"] == 0
    assert data["quota"]["vcpus"] == 0
    assert data["quota"]["ai_use_per_day"] == 0
    assert data["quota"]["ai_uses_left_today"] == 0


def test_user_info_serializer_with_quota_embeds_serialized_quota():
    user = create_user(username="frank")
    quota = create_quota(
        user=user, max_containers=3, max_memory_mb=1024, vcpus=4, ai_use_per_day=10
    )

    payload = {
        "username": user.username,
        "is_superuser": user.is_superuser,
        "active_containers": 0,
        "has_quota": True,
        "quota": quota,
    }
    ser = UserInfoSerializer(instance=payload)
    data = ser.data

    assert data["has_quota"] is True
    assert data["quota"]["max_containers"] == 3
    assert data["quota"]["max_memory_mb"] == 1024
    assert data["quota"]["vcpus"] == 4
    assert data["quota"]["ai_use_per_day"] == 10
    assert data["quota"]["ai_uses_left_today"] == 10


def test_file_template_serializer_includes_items_in_order():
    tpl = FileTemplate.objects.create(name="Default template", description="desc")
    # Order should be by (order, path)
    i2 = FileTemplateItem.objects.create(
        template=tpl, path="b.txt", content="B", mode=0o644, order=2
    )
    i1 = FileTemplateItem.objects.create(
        template=tpl, path="a.txt", content="A", mode=0o600, order=1
    )

    ser = FileTemplateSerializer(instance=tpl)
    data = ser.data

    assert data["id"] == tpl.id
    assert data["name"] == "Default template"
    assert len(data["items"]) == 2
    # Ensure ordering (i1 first, then i2)
    assert [it["path"] for it in data["items"]] == ["a.txt", "b.txt"]
    # Ensure read-only fields present
    assert set(data["items"][0].keys()) == {"id", "path", "content", "mode", "order"}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("app", "/app"),
        ("/app/", "/app"),
        ("/", "/"),
        ("", "/app"),
        (" sub/dir ", "/sub/dir"),
    ],
)
def test_apply_template_request_serializer_normalizes_dest_path(raw, expected):
    ser = ApplyTemplateRequestSerializer(
        data={"container_id": 1, "dest_path": raw, "clean": True}
    )
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["dest_path"] == expected


def test_apply_template_request_serializer_defaults():
    # Omit dest_path and clean -> should default to "/app" and True
    ser = ApplyTemplateRequestSerializer(data={"container_id": 42})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["dest_path"] == "/app"
    assert ser.validated_data["clean"] is True


def test_apply_template_request_serializer_invalid_container_id():
    ser = ApplyTemplateRequestSerializer(data={"container_id": 0})
    assert not ser.is_valid()
    assert "container_id" in ser.errors


def test_apply_ai_code_request_serializer_content_validation():
    # Empty/blank content not allowed
    ser_blank = ApplyAICodeRequestSerializer(data={"container_id": 1, "content": "   "})
    assert not ser_blank.is_valid()
    assert "content" in ser_blank.errors

    # Keeps whitespace because trim_whitespace=False
    raw_content = "  print('hello')  "
    ser_ok = ApplyAICodeRequestSerializer(
        data={"container_id": 2, "content": raw_content, "dest_path": "tmp"}
    )
    assert ser_ok.is_valid(), ser_ok.errors
    assert ser_ok.validated_data["content"] == raw_content
    assert ser_ok.validated_data["dest_path"] == "/tmp"
    # clean default is False for AI code
    assert ser_ok.validated_data["clean"] is False


def test_apply_template_response_serializer_schema():
    payload = {
        "status": "applied",
        "template_id": 10,
        "container": 5,
        "dest_path": "/app",
        "files_count": 3,
    }
    ser = ApplyTemplateResponseSerializer(data=payload)
    assert ser.is_valid(), ser.errors
    assert ser.validated_data == payload


def test_apply_ai_code_response_serializer_schema():
    payload = {"status": "ok", "container": 7, "dest_path": "/code"}
    ser = ApplyAICodeResponseSerializer(data=payload)
    assert ser.is_valid(), ser.errors
    assert ser.validated_data == payload
