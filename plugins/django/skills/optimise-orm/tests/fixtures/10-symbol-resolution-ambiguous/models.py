from django.db import models


class Order(models.Model):
    status = models.CharField(max_length=30)
    customer_id = models.IntegerField()

    class Meta:
        app_label = "fixture10"
