from django.urls import path

from . import views

urlpatterns = [
    path("<int:order_id>/", views.order_detail),
    path("<int:order_id>/discount/", views.discounted_total),
    path("customer/<int:customer_id>/", views.customer_orders),
    path("cart/add/", views.add_item),
]
