from django.db import migrations

# Types pre-warmed by default and how many to keep ready per node.
DEFAULT_POOL_TARGETS = {"small": 2, "medium": 2}


def enable_default_pools(apps, schema_editor):
    """
    Mark the stock small/medium types as poolable on already-seeded databases.

    The seed signal only runs when no types exist, so existing installs need this
    to opt the common types into the warm pool. Heavy types (e.g. large) are left
    non-poolable.
    """
    ContainerType = apps.get_model("vm_manager", "ContainerType")
    for name, target in DEFAULT_POOL_TARGETS.items():
        ContainerType.objects.filter(container_type_name=name).update(
            poolable=True, pool_target=target
        )


def disable_default_pools(apps, schema_editor):
    ContainerType = apps.get_model("vm_manager", "ContainerType")
    ContainerType.objects.filter(
        container_type_name__in=list(DEFAULT_POOL_TARGETS)
    ).update(poolable=False, pool_target=0)


class Migration(migrations.Migration):
    dependencies = [
        ("vm_manager", "0010_container_is_pool_containertype_pool_target_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_default_pools, disable_default_pools),
    ]
