from django.urls import path

from . import views

app_name = "gestion"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("ingresar/", views.Ingresar.as_view(), name="ingresar"),
    path("salir/", views.salir, name="salir"),
    path("prendas/", views.prendas, name="prendas"),
    path("prendas/nueva/", views.prenda_editar, name="prenda_nueva"),
    path("prendas/<int:pk>/", views.prenda_editar, name="prenda_editar"),
    path("prendas/<int:pk>/borrar/", views.prenda_borrar, name="prenda_borrar"),
    path("prendas/<int:pk>/toggle/", views.prenda_toggle, name="prenda_toggle"),
    path("prendas/<int:pk>/precio/", views.prenda_precio, name="prenda_precio"),
    path("fotos/<int:pk>/mover/", views.foto_mover, name="foto_mover"),
    path("fotos/<int:pk>/borrar/", views.foto_borrar, name="foto_borrar"),
    path("pedidos/", views.pedidos, name="pedidos"),
    path("pedidos/<int:pk>/", views.pedido_actualizar, name="pedido_actualizar"),
    path("portada/", views.portada, name="portada"),
]
