"""
Symbol resolution ambiguity fixture.

Two classes named OrderListView exist — one here and one in target_alt.py.
When the skill is invoked as: /django-inquisition:optimise-orm OrderListView

The skill should:
  1. Detect multiple definitions via grep.
  2. Prompt the user to disambiguate:
     "Symbol 'OrderListView' found in multiple locations:
       1. fixture10/target.py:13
       2. fixture10/target_alt.py:8
     Please re-invoke with the dotted form, e.g.:
       /django-inquisition:optimise-orm fixture10.target.OrderListView"
  3. NOT proceed with analysis until the user clarifies.

expected.json is empty because the skill should halt at disambiguation,
not emit findings.
"""

from django.views import View

from .models import Order


class OrderListView(View):
    """First definition — in target.py."""

    def get(self, request):
        orders = Order.objects.filter(status="open")
        return orders
