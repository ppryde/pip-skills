from django.db import models


class Invoice(models.Model):
    customer_id = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=30, default="draft")
    issued_at = models.DateTimeField(null=True)
    voided = models.BooleanField(default=False)

    def delete(self, *args, **kwargs):
        # Custom logic that QuerySet.delete() skips (WRITE-009).
        return super().delete(*args, **kwargs)

    class Meta:
        app_label = "fixture06"
