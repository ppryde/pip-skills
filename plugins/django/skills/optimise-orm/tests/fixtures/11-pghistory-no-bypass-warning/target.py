"""
pghistory fixture — no escalation of WRITE-006/007.

pghistory records history via Postgres triggers, NOT Django signals.
It is tagged signals_safe=True in the skill's PAT-070 logic.

Therefore:
  - WRITE-006 should NOT escalate to critical (stays at medium).
  - WRITE-007 should NOT escalate to critical (stays at medium).

This contrasts with fixture 06 where easyaudit causes escalation.

The skill must detect pghistory in INSTALLED_APPS and apply the
signals_safe exception — PAT-070 info banner still fires (audit framework
detected) but without the critical escalation.
"""

from .models import Invoice


def void_invoices(invoice_ids):
    """WRITE-006: .update() on Invoice. pghistory present but signals_safe — stays medium."""
    Invoice.objects.filter(pk__in=invoice_ids).update(voided=True)


def import_invoices(data):
    """WRITE-007: bulk_create on Invoice. pghistory present but signals_safe — stays medium."""
    Invoice.objects.bulk_create([
        Invoice(customer_id=row["customer_id"], amount=row["amount"])
        for row in data
    ])
