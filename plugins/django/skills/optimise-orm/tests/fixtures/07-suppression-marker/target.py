"""
Suppression marker fixture.

WRITE-006 on line 16 is suppressed with: # noqa: speedy-orm WRITE-006
The skill should:
  - NOT emit WRITE-006 as a finding in the body
  - Count it in the report frontmatter suppressed: 1
  - Still emit any other unsuppressed findings

WRITE-007 on line 21 is NOT suppressed and should appear as a finding.
"""

from .models import Invoice


def void_invoices(invoice_ids):
    Invoice.objects.filter(pk__in=invoice_ids).update(voided=True)  # noqa: speedy-orm WRITE-006


def import_invoices(data):
    Invoice.objects.bulk_create([  # WRITE-007 — not suppressed
        Invoice(customer_id=row["customer_id"], amount=row["amount"])
        for row in data
    ])
