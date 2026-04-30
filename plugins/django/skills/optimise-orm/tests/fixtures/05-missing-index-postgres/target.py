"""
Shipment queries — missing index patterns on Postgres.

IDX-001: filter on status (unindexed CharField).
IDX-002: order_by on shipped_at without index + LIMIT.
IDX-010: multi-column filter on (status, warehouse_id) with no composite index.
IDX-040: JSONField metadata filtered with __has_key but no GinIndex.
"""

from .models import Shipment


def get_pending_shipments():
    """IDX-001: status unindexed."""
    return Shipment.objects.filter(status="pending")


def get_recent_shipments(limit=25):
    """IDX-002: order_by shipped_at without index, combined with LIMIT."""
    return Shipment.objects.order_by("shipped_at")[:limit]


def get_warehouse_pending(warehouse_id):
    """IDX-010: multi-column filter — no composite (status, warehouse_id) index."""
    return Shipment.objects.filter(status="pending", warehouse_id=warehouse_id)


def get_shipments_with_insurance():
    """IDX-040: JSONField filtered with __has_key — no GinIndex on metadata."""
    return Shipment.objects.filter(metadata__has_key="insurance_value")
