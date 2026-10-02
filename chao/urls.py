from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    # "panel" en lugar de "admin": es como le vamos a decir a la dueña, y de paso
    # deja de ser la URL que escanean todos los bots.
    path("panel/", admin.site.urls),
    # El panel de todos los días de la dueña. /panel/ queda como herramienta
    # avanzada (looks y sus puntos sobre la foto).
    path("gestion/", include("gestion.urls")),
    path("carrito/", include("carrito.urls")),
    path("checkout/", include("pedidos.urls")),
    path("", include("catalogo.urls")),
]

# En desarrollo Django sirve lo que la dueña suba desde el panel. En producción
# eso lo hace el disco de Render o un storage externo — ver README. SERVIR_MEDIA
# existe solo para la demo de Vercel, donde no hay ninguna de las dos cosas.
if settings.DEBUG or settings.SERVIR_MEDIA:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
