from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vm_manager", "0012_container_expires_at"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="container",
            name="base_image",
        ),
    ]
