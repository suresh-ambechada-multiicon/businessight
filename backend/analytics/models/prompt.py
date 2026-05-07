from django.db import models


class SavedPrompt(models.Model):
    name = models.CharField(max_length=255, unique=True)
    query = models.TextField()
    sql_command = models.TextField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["-created_at"]