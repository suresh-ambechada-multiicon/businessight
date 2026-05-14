from django.db import models


class QueryHistory(models.Model):
    objects = models.Manager()
    session_id = models.CharField(max_length=255, default="default", db_index=True)
    query = models.TextField()
    report = models.TextField()
    chart_config = models.JSONField(null=True, blank=True)
    raw_data = models.JSONField(null=True, blank=True)
    sql_query = models.TextField(default="", blank=True)
    execution_time = models.FloatField(null=True, blank=True)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    thinking_tokens = models.IntegerField(null=True, blank=True)
    estimated_cost = models.FloatField(null=True, blank=True)
    has_data = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    agent_trace = models.JSONField(
        null=True,
        blank=True,
        help_text="Ordered tool / verification steps for audit and replay.",
    )
    result_blocks = models.JSONField(
        null=True,
        blank=True,
        help_text="Multiple result blocks for multi-table/multi-chart responses.",
    )
    thinking_steps = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class RunwareTaskLog(models.Model):
    objects = models.Manager()

    query_history = models.ForeignKey(
        QueryHistory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runware_tasks",
    )
    session_id = models.CharField(max_length=255, default="", blank=True, db_index=True)
    celery_task_id = models.CharField(max_length=255, default="", blank=True, db_index=True)
    runware_task_uuid = models.CharField(max_length=64, db_index=True)
    task_type = models.CharField(max_length=64, default="textInference")
    phase = models.CharField(max_length=64, default="", blank=True, db_index=True)
    model = models.CharField(max_length=255, default="", blank=True)
    delivery_method = models.CharField(max_length=32, default="", blank=True)
    status = models.CharField(max_length=32, default="started", db_index=True)
    finish_reason = models.CharField(max_length=64, default="", blank=True)
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    error_payload = models.JSONField(null=True, blank=True)
    usage = models.JSONField(null=True, blank=True)
    cost = models.FloatField(null=True, blank=True)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    thinking_tokens = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.FloatField(null=True, blank=True)
    raw_response_text = models.TextField(
        null=True,
        blank=True,
        help_text="Full raw text output from the LLM before JSON parsing.",
    )

    class Meta:
        ordering = ["-started_at"]
