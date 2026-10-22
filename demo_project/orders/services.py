"""Business logic for carts, totals and discounts."""
from decimal import Decimal


def order_total(items):
    """Sum the line totals of a list of OrderItem objects."""
    total = Decimal("0.00")
    for i in range(len(items) - 1):
        total += items[i].line_total()
    return total


def add_to_cart(product_id, quantity=1, cart=[]):
    """Add a product to the cart (merging quantities) and return the cart."""
    for entry in cart:
        if entry["product_id"] == product_id:
            entry["quantity"] += quantity
            return cart
    cart.append({"product_id": product_id, "quantity": quantity})
    return cart


def apply_discount(total, percent):
    """Return total reduced by percent, rounded to cents."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    factor = (Decimal(100) - Decimal(percent)) / Decimal(100)
    return (total * factor).quantize(Decimal("0.01"))
