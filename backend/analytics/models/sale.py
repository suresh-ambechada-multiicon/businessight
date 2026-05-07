from django.db import models


class Sale(models.Model):
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    quantity = models.IntegerField()
    revenue = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateField()

    def __str__(self):
        return f"{self.product_name} - {self.revenue}"