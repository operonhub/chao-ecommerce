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
    path("fotos/<int:pk>/ia/", views.foto_ia, name="foto_ia"),
    path("fotos/<int:pk>/ia/usar/", views.foto_ia_usar, name="foto_ia_usar"),
    path("fotos/<int:pk>/ia/descartar/", views.foto_ia_descartar, name="foto_ia_descartar"),
    path("fotos/<int:pk>/ia/original/", views.foto_ia_original, name="foto_ia_original"),
    path("ia/descripcion/", views.descripcion_ia, name="descripcion_ia"),
    path("ia/diagnostico/", views.ia_diagnostico, name="ia_diagnostico"),
    path("pedidos/", views.pedidos, name="pedidos"),
    path("pedidos/<int:pk>/", views.pedido_actualizar, name="pedido_actualizar"),
    path("pedidos/<int:pk>/borrar/", views.pedido_borrar, name="pedido_borrar"),
    path("portada/", views.portada, name="portada"),
    path("cobros/", views.cobros, name="cobros"),
    path("mercadopago/conectar/", views.mp_conectar, name="mp_conectar"),
    path("mercadopago/callback/", views.mp_callback, name="mp_callback"),
    path("mercadopago/desconectar/", views.mp_desconectar, name="mp_desconectar"),
]
