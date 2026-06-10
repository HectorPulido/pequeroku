from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("internal_config", "0007_aimemory_current_conversation"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="aimemory",
            name="memory",
        ),
    ]
