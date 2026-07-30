from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("", views.home, name="home"),
    path("prenda/<slug:slug>/", views.producto, name="producto"),
]
