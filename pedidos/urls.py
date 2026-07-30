from django.urls import path

from . import views

app_name = "pedidos"

urlpatterns = [
    path("", views.checkout, name="checkout"),
    path("pagar/", views.pagar, name="pagar"),
    path("resultado/", views.resultado, name="resultado"),
    path("mp/webhook/", views.mp_webhook, name="mp_webhook"),
]
