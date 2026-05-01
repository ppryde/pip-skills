from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=200)
    attributes = models.JSONField(default=dict)

    class Meta:
        app_label = "fixture08"
