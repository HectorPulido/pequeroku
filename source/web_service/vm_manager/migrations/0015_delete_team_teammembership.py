from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vm_manager", "0014_remove_container_resource_quota"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TeamMembership",
        ),
        migrations.DeleteModel(
            name="Team",
        ),
    ]
