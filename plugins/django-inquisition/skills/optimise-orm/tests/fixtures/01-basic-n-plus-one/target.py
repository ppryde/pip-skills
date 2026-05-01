"""
Order list view — classic N+1 pattern.

The view fetches all open orders but does not select_related the customer FK.
The template (orders.html) accesses {{ order.customer.name }} for each row,
triggering one additional query per order.

Additionally, the view itself accesses order.customer.email in a loop,
producing a second N+1 site in Python code.
"""

from django.shortcuts import render

from .models import Order


def order_list(request):
    orders = Order.objects.filter(status="open")
    return render(request, "orders.html", {"orders": orders})


def order_summary(request):
    """Python-side N+1 — accesses FK in a loop without select_related."""
    orders = Order.objects.filter(status="open")
    summaries = []
    for order in orders:
        summaries.append({
            "id": order.id,
            "customer_name": order.customer.name,  # FETCH-001: missing select_related
        })
    return render(request, "summary.html", {"summaries": summaries})
