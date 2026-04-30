from django.db import models


class Shipment(models.Model):
    # status and warehouse_id are filtered frequently but have no index
    status = models.CharField(max_length=30)
    warehouse_id = models.IntegerField()
    carrier = models.CharField(max_length=100)
    tracking_number = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict)
    shipped_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "fixture05"
        # Note: no indexes defined — that's the problem
