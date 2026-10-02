from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("", views.home, name="home"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/<slug:categoria_slug>/", views.catalogo, name="catalogo_categoria"),
    path("looks/", views.looks, name="looks"),
    path("prenda/<slug:slug>/", views.producto, name="producto"),
]
