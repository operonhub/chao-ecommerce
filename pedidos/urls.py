from django.urls import path

from . import views

app_name = "pedidos"

urlpatterns = [
    path("", views.checkout, name="checkout"),
    path("pago/<str:codigo>/", views.pago, name="pago"),
    path("pago/<str:codigo>/procesar/", views.procesar, name="procesar"),
    path("pedido/<str:codigo>/", views.pedido, name="pedido"),
    path("pedido/<str:codigo>/estado/", views.estado, name="estado"),
    path("mp/webhook/", views.mp_webhook, name="mp_webhook"),
]
