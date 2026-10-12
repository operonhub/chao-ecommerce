from django.urls import path

from . import seo, views

app_name = "catalogo"

urlpatterns = [
    path("robots.txt", seo.robots_txt, name="robots"),
    path("sitemap.xml", seo.sitemap_xml, name="sitemap"),
    path("", views.home, name="home"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/<slug:categoria_slug>/", views.catalogo, name="catalogo_categoria"),
    path("looks/", views.looks, name="looks"),
    path("prenda/<slug:slug>/", views.producto, name="producto"),
]
