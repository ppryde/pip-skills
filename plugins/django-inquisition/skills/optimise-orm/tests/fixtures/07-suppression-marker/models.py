from django.db import models


class Invoice(models.Model):
    customer_id = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=30, default="draft")
    voided = models.BooleanField(default=False)

    class Meta:
        app_label = "fixture07"
