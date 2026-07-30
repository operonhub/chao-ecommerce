from django.urls import path

from . import views

app_name = "carrito"

urlpatterns = [
    path("", views.ver, name="ver"),
    path("agregar/", views.agregar, name="agregar"),
    path("agregar-look/", views.agregar_look, name="agregar_look"),
    path("actualizar/", views.actualizar, name="actualizar"),
    path("quitar/", views.quitar, name="quitar"),
]
