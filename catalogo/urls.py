from django.urls import path

from . import seo, views

app_name = "catalogo"

urlpatterns = [
    path("robots.txt", seo.robots_txt, name="robots"),
    path("sitemap.xml", seo.sitemap_xml, name="sitemap"),
    # En la raíz y sin hash: Google exige una URL de favicon estable.
    path("favicon.ico", seo.icono_raiz, {"nombre": "favicon.ico"}, name="favicon"),
    path("apple-touch-icon.png", seo.icono_raiz, {"nombre": "apple-touch-icon.png"}, name="apple_icon"),
    path("", views.home, name="home"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/<slug:categoria_slug>/", views.catalogo, name="catalogo_categoria"),
    path("looks/", views.looks, name="looks"),
    path("prenda/<slug:slug>/", views.producto, name="producto"),
]
