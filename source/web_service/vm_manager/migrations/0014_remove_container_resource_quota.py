from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vm_manager", "0013_remove_container_base_image"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="container",
            name="resource_quota",
        ),
    ]
