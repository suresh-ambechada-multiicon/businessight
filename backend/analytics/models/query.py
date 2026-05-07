from django.db import models


class QueryHistory(models.Model):
    session_id = models.CharField(max_length=255, default="default", db_index=True)
    query = models.TextField()
    report = models.TextField()
    chart_config = models.JSONField(null=True, blank=True)
    raw_data = models.JSONField(null=True, blank=True)
    sql_query = models.TextField(default="", blank=True)
    execution_time = models.FloatField(null=True, blank=True)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    estimated_cost = models.FloatField(null=True, blank=True)
    has_data = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["created_at"]