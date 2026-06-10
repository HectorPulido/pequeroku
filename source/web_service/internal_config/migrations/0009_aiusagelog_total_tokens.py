from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("internal_config", "0008_remove_aimemory_memory"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiusagelog",
            name="total_tokens",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Provider-reported total tokens; authoritative for "
                "reconciliation. May exceed prompt+completion (e.g. reasoning "
                "tokens) or be the only figure some endpoints report.",
            ),
        ),
    ]
