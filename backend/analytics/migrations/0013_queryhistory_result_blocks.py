from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0012_queryhistory_agent_trace"),
    ]

    operations = [
        migrations.AddField(
            model_name="queryhistory",
            name="result_blocks",
            field=models.JSONField(
                blank=True,
                help_text="Multiple result blocks for multi-table/multi-chart responses.",
                null=True,
            ),
        ),
    ]