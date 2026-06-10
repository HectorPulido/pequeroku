import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("internal_config", "0009_aiusagelog_total_tokens"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiusagelog",
            name="container",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="r_container",
                to="vm_manager.container",
            ),
        ),
    ]
