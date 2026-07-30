from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # "panel" en lugar de "admin": es como le vamos a decir a la dueña, y de paso
    # deja de ser la URL que escanean todos los bots.
    path("panel/", admin.site.urls),
    path("carrito/", include("carrito.urls")),
    path("checkout/", include("pedidos.urls")),
    path("", include("catalogo.urls")),
]

# En desarrollo Django sirve lo que la dueña suba desde el panel. En producción
# eso lo hace WhiteNoise (estáticos) o el disco de Render (media) — ver README.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
