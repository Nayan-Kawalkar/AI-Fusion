# Planted bugs (team notes — excluded from indexing via .codelensignore)

| # | File | Line | Bug | Fix |
|---|------|------|-----|-----|
| 1 | `orders/services.py` | 8 | **Off-by-one in a loop**: `for i in range(len(items) - 1)` never visits the last item, so every order total is missing its last line. | `for item in items: total += item.line_total()` (or `range(len(items))`). |
| 2 | `orders/views.py` | 25 | **Wrong queryset method**: `Order.objects.get(customer=customer)` returns one object and raises `MultipleObjectsReturned` (or `DoesNotExist`); the code then iterates over it. | `Order.objects.filter(customer=customer)` (or `customer.orders.all()`). |
| 3 | `orders/services.py` | 13 | **Mutable default argument**: `cart=[]` is created once, so every call without a cart shares (and grows) the same list across requests. | `cart=None` then `if cart is None: cart = []`. |

Static analysis will also flag the unused `Sum` import in `orders/views.py` and the mutable default (bug 3).
Bugs 1 and 2 are only found by the AI using the retrieved docs (`range()` pitfalls, `QuerySet.get` vs `filter`).
