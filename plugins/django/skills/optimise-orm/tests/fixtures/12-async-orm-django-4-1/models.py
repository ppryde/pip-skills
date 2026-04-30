from django.db import models


class Order(models.Model):
    customer_id = models.IntegerField()
    status = models.CharField(max_length=30, default="open")
    total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        app_label = "fixture12"
