# Generated manually for agent audit trace

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0011_alter_savedprompt_name_alter_savedprompt_sql_command"),
    ]

    operations = [
        migrations.AddField(
            model_name="queryhistory",
            name="agent_trace",
            field=models.JSONField(
                blank=True,
                help_text="Ordered tool / verification steps for audit and replay.",
                null=True,
            ),
        ),
    ]
