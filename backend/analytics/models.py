from django.db import models


class Sale(models.Model):
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    quantity = models.IntegerField()
    revenue = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateField()

    def __str__(self):
        return f"{self.product_name} - {self.revenue}"


class QueryHistory(models.Model):
    session_id = models.CharField(max_length=255, default="default", db_index=True)
    query = models.TextField()
    report = models.TextField()
    chart_config = models.JSONField(null=True, blank=True)
    raw_data = models.JSONField(null=True, blank=True)
    sql_query = models.TextField(default="", blank=True)
    execution_time = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
