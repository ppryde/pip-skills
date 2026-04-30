"""
Alternate file — also defines OrderListView.
This creates the ambiguity that the skill must detect and surface.
"""

from django.views import View

from .models import Order


class OrderListView(View):
    """Second definition — in target_alt.py."""

    def get(self, request):
        return Order.objects.all()
