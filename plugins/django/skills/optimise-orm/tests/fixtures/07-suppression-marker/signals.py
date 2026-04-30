from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Invoice


@receiver(post_save, sender=Invoice)
def log_invoice_change(sender, instance, created, **kwargs):
    pass
