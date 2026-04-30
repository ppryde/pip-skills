"""
Invoice management — audit-framework bypass patterns.

Invoice has post_save + pre_delete listeners registered in signals.py.
easy_audit is in INSTALLED_APPS.

WRITE-006: .update() on Invoice — bypasses signals. Escalates to critical (easy_audit present).
WRITE-007: bulk_create on Invoice — bypasses signals. Escalates to critical.
WRITE-009: qs.delete() on Invoice — bypasses pre_delete. Escalates to critical.
"""

from .models import Invoice


def void_invoices(invoice_ids):
    """WRITE-006: .update() on model with signal listeners — escalates to critical with easy_audit."""
    Invoice.objects.filter(pk__in=invoice_ids).update(voided=True)


def import_invoices(data):
    """WRITE-007: bulk_create on model with signal listeners — escalates to critical with easy_audit."""
    Invoice.objects.bulk_create([
        Invoice(customer_id=row["customer_id"], amount=row["amount"])
        for row in data
    ])


def purge_draft_invoices():
    """WRITE-009: qs.delete() on model with pre_delete listener — escalates to critical with easy_audit."""
    Invoice.objects.filter(status="draft", voided=True).delete()
