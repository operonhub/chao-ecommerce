{% load static %}/* Trabajador del panel "Mi tienda": recibe los avisos de ventas y los muestra.
   Lo sirve Django en /gestion/sw.js (alcance /gestion/). */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let datos = {};
  try {
    datos = e.data ? e.data.json() : {};
  } catch {
    datos = { cuerpo: e.data ? e.data.text() : "" };
  }
  e.waitUntil(
    self.registration.showNotification(datos.titulo || "CHAO · Mi tienda", {
      body: datos.cuerpo || "",
      icon: "{% static 'icono-panel-192.png' %}",
      badge: "{% static 'icono-panel-192.png' %}",
      tag: datos.etiqueta || undefined,
      data: { url: datos.url || "{% url 'gestion:pedidos' %}" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "{% url 'gestion:pedidos' %}", self.location.origin).href;
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((ventanas) => {
      for (const v of ventanas) {
        if (v.url.startsWith(self.location.origin) && "focus" in v) {
          v.navigate(url);
          return v.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
