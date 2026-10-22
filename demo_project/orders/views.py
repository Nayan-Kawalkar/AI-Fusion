import json

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import Customer, Order, Product
from .services import add_to_cart, apply_discount


@require_GET
def order_detail(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    items = [
        {"product": item.product.name, "quantity": item.quantity, "line_total": str(item.line_total())}
        for item in order.items.select_related("product")
    ]
    return JsonResponse({"id": order.pk, "status": order.status, "items": items, "total": str(order.total())})


@require_GET
def customer_orders(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = Order.objects.get(customer=customer)
    data = [{"id": o.pk, "status": o.status, "total": str(o.total())} for o in orders]
    return JsonResponse({"customer": customer.name, "orders": data})


@require_POST
def add_item(request):
    payload = json.loads(request.body or "{}")
    product = get_object_or_404(Product, pk=payload.get("product_id"))
    cart = add_to_cart(product.pk, int(payload.get("quantity", 1)))
    return JsonResponse({"cart": cart})


@require_GET
def discounted_total(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    percent = int(request.GET.get("percent", 0))
    return JsonResponse({"total": str(apply_discount(order.total(), percent))})
