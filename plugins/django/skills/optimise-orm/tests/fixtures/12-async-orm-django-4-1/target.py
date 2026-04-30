"""
Async views — sync ORM in async context (PAT-050, Django >= 4.1).

order_detail_view: async def view calling sync .get() — blocks event loop.
order_list_view: async def view calling sync .filter() — blocks event loop.
order_create_view: async def view calling sync .save() — blocks event loop.

correct_async_view: uses aget() correctly — should NOT trigger PAT-050.
"""

from django.http import JsonResponse

from .models import Order


async def order_detail_view(request, pk):
    """PAT-050: sync .get() inside async view — blocks event loop."""
    order = Order.objects.get(pk=pk)  # PAT-050 fires here — sync .get() in async view
    return JsonResponse({"id": order.id, "status": order.status})


async def order_list_view(request):
    """PAT-050: sync .filter() inside async view — blocks event loop."""
    orders = list(Order.objects.filter(status="open"))
    return JsonResponse({"orders": [o.id for o in orders]})


async def order_create_view(request):
    """PAT-050: sync .save() inside async view — blocks event loop."""
    order = Order(customer_id=1, total="99.00")
    order.save()
    return JsonResponse({"id": order.id})


async def correct_async_view(request, pk):
    """Correct async usage — should NOT trigger PAT-050."""
    order = await Order.objects.aget(pk=pk)
    return JsonResponse({"id": order.id, "status": order.status})
