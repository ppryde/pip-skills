from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Invoice


@receiver(post_save, sender=Invoice)
def log_invoice_change(sender, instance, created, **kwargs):
    """Audit listener — logs every Invoice save. Bypassed by .update() and bulk ops."""
    pass  # in real code: AuditLog.objects.create(...)


@receiver(pre_delete, sender=Invoice)
def log_invoice_delete(sender, instance, **kwargs):
    """Audit listener — logs every Invoice delete. Bypassed by qs.delete()."""
    pass  # in real code: AuditLog.objects.create(...)
