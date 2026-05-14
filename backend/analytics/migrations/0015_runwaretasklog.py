from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0014_delete_sale_queryhistory_thinking_steps_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="RunwareTaskLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "session_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=255
                    ),
                ),
                (
                    "celery_task_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=255
                    ),
                ),
                (
                    "runware_task_uuid",
                    models.CharField(db_index=True, max_length=64),
                ),
                (
                    "task_type",
                    models.CharField(default="textInference", max_length=64),
                ),
                (
                    "phase",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=64
                    ),
                ),
                (
                    "model",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "delivery_method",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "status",
                    models.CharField(
                        db_index=True, default="started", max_length=32
                    ),
                ),
                (
                    "finish_reason",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("request_payload", models.JSONField(blank=True, null=True)),
                ("response_payload", models.JSONField(blank=True, null=True)),
                ("error_payload", models.JSONField(blank=True, null=True)),
                ("usage", models.JSONField(blank=True, null=True)),
                ("cost", models.FloatField(blank=True, null=True)),
                ("input_tokens", models.IntegerField(blank=True, null=True)),
                ("output_tokens", models.IntegerField(blank=True, null=True)),
                ("thinking_tokens", models.IntegerField(blank=True, null=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.FloatField(blank=True, null=True)),
                (
                    "query_history",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="runware_tasks",
                        to="analytics.queryhistory",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
    ]
