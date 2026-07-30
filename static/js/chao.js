/* ==========================================================================
   CHAO Indumentaria — JS de la tienda
   --------------------------------------------------------------------------
   Principio: el carrito vive en la sesión del servidor y el servidor devuelve
   el cajón ya renderizado. Este archivo no guarda estado del carrito — solo
   manda acciones y reemplaza nodos. Así no hay dos verdades que puedan diferir.

   Sobre el reemplazo de HTML: se parsea con DOMParser y se insertan nodos con
   replaceChildren, sin asignar innerHTML. El HTML sale de nuestro propio
   endpoint de Django (que autoescapa todo lo interpolado), pero parsear en un
   documento aparte deja explícito qué se inserta y no ejecuta <script>.
   ========================================================================== */

(() => {
  "use strict";

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  // Las URLs las publica el template (base.html) para no hardcodear rutas acá.
  const URLS = window.CHAO_URLS || {};

  const csrf = () => {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const campo = $('input[name="csrfmiddlewaretoken"]');
    return campo ? campo.value : "";
  };

  const pesos = (n) => "$" + Math.round(n).toLocaleString("es-AR");

  const PRENDAS = (() => {
    const nodo = $("#prendas-data");
    try {
      return nodo ? JSON.parse(nodo.textContent) : {};
    } catch {
      return {};
    }
  })();

  /* --- Aviso flotante ---------------------------------------------------- */
  const chicharra = $("[data-chicharra]");
  let chicharraTimer;

  function avisar(texto) {
    if (!chicharra) return;
    chicharra.textContent = texto;
    chicharra.dataset.visible = "1";
    clearTimeout(chicharraTimer);
    chicharraTimer = setTimeout(() => delete chicharra.dataset.visible, 2600);
  }

  /* --- Cajón del carrito ------------------------------------------------- */
  const cajon = $("[data-cajon]");
  const velo = $("[data-velo]");
  let ultimoFoco = null;

  function abrirCajon() {
    if (!cajon) return;
    ultimoFoco = document.activeElement;
    cajon.dataset.abierto = "1";
    cajon.setAttribute("aria-hidden", "false");
    if (velo) velo.dataset.abierto = "1";
    const cerrar = $("[data-cerrar-carrito]", cajon);
    if (cerrar) cerrar.focus();
  }

  function cerrarCajon() {
    if (!cajon) return;
    delete cajon.dataset.abierto;
    cajon.setAttribute("aria-hidden", "true");
    if (velo) delete velo.dataset.abierto;
    if (ultimoFoco && document.contains(ultimoFoco)) ultimoFoco.focus();
  }

  /** Cambia el contenido del cajón por el que devolvió el servidor. */
  function pintarCajon(html, abrir) {
    if (!cajon) return;
    const doc = new DOMParser().parseFromString(html, "text/html");
    cajon.replaceChildren(...doc.body.childNodes);
    sincronizarContador();
    if (abrir) abrirCajon();
  }

  /** El contador del header está fuera del cajón, así que se actualiza aparte. */
  function sincronizarContador() {
    const titulo = $(".cajon__titulo", cajon);
    const cuenta = $("[data-cuenta]");
    if (!cuenta || !titulo) return;
    const n = (titulo.textContent.match(/\((\d+)\)/) || [, "0"])[1];
    cuenta.textContent = n;
    cuenta.dataset.vacio = n === "0" ? "1" : "0";
  }

  async function accionCarrito(url, datos, { abrir = true } = {}) {
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: datos,
      });
      if (!res.ok) {
        avisar(res.status === 400 ? "Elegí un talle antes de agregar." : "No se pudo actualizar el carrito.");
        return;
      }
      pintarCajon(await res.text(), abrir);
    } catch {
      avisar("Se cortó la conexión. Probá de nuevo.");
    }
  }

  /* --- Formularios que agregan al carrito -------------------------------- */
  // Se interceptan por submit y no por click: así funciona con Enter, y si el JS
  // no carga el formulario hace un POST normal y la página sigue andando.
  document.addEventListener("submit", (e) => {
    const form = e.target.closest("[data-form-carrito]");
    if (!form) return;
    e.preventDefault();
    accionCarrito(form.action, new FormData(form));
    avisar(form.querySelector('[name="look"]') ? "Agregamos el look completo." : "Agregamos la prenda al carrito.");
  });

  /* --- LOOKBOOK: hotspots ------------------------------------------------
     El marcador está posicionado en % sobre la foto. Al tocarlo se abre UNA
     ficha por look (no una por prenda) que se reposiciona y se llena con los
     datos del JSON. Se resalta además la fila del panel de al lado, para que
     la relación foto ↔ lista quede clara.                                  */

  function cerrarFichas() {
    $$("[data-ficha]").forEach((f) => delete f.dataset.abierta);
    $$(".hotspot").forEach((h) => h.setAttribute("aria-expanded", "false"));
    $$("[data-fila]").forEach((f) => delete f.dataset.activa);
  }

  function ubicarFicha(ficha, hotspot, contenedor) {
    // Se ancla al marcador pero nunca se sale de la foto.
    const c = contenedor.getBoundingClientRect();
    const h = hotspot.getBoundingClientRect();

    let x = h.left - c.left + h.width / 2 - ficha.offsetWidth / 2;
    x = Math.max(12, Math.min(x, c.width - ficha.offsetWidth - 12));

    // Debajo del marcador si entra; si no, arriba.
    let y = h.top - c.top + h.height + 10;
    if (y + ficha.offsetHeight > c.height - 12) {
      y = h.top - c.top - ficha.offsetHeight - 10;
    }

    ficha.style.left = `${x}px`;
    ficha.style.top = `${Math.max(12, y)}px`;
  }

  function construirTalles(prenda) {
    if (!prenda.necesitaElegir) {
      const p = document.createElement("p");
      p.className = "prenda-fila__talles";
      p.textContent = "Talle único";
      return [p];
    }
    return prenda.talles.map((t) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "talle";
      btn.textContent = t.nombre;
      btn.dataset.talle = t.id;
      btn.setAttribute("aria-pressed", "false");
      if (t.stock <= 0) {
        btn.disabled = true;
        btn.title = "Sin stock en este talle";
      }
      return btn;
    });
  }

  function abrirFicha(hotspot) {
    const contenedor = hotspot.closest(".look__foto");
    const ficha = $("[data-ficha]", contenedor);
    const look = hotspot.closest(".look");
    const id = hotspot.dataset.hotspot;
    const prenda = PRENDAS[id];
    if (!ficha || !prenda) return;

    const yaAbierta = hotspot.getAttribute("aria-expanded") === "true";
    cerrarFichas();
    if (yaAbierta) return; // Segundo toque en el mismo marcador: cierra.

    $("[data-ficha-nombre]", ficha).textContent = prenda.nombre;
    $("[data-ficha-precio]", ficha).textContent = pesos(prenda.precio);
    $("[data-ficha-cuotas]", ficha).textContent = `3 x ${pesos(prenda.cuota)} sin interés`;
    $("[data-ficha-talles]", ficha).replaceChildren(...construirTalles(prenda));

    const agregar = $("[data-ficha-agregar]", ficha);
    agregar.dataset.producto = id;
    // Con varias opciones no se adivina: hasta que elija una, el botón no habilita.
    // Con talle único ya viaja resuelto y se puede agregar de una.
    if (prenda.necesitaElegir) {
      delete agregar.dataset.talle;
      agregar.disabled = true;
      agregar.textContent = "Elegí tu talle";
    } else {
      if (prenda.talleUnico) agregar.dataset.talle = prenda.talleUnico;
      else delete agregar.dataset.talle;
      agregar.disabled = false;
      agregar.textContent = "Agregar al carrito";
    }

    ficha.dataset.abierta = "1";
    hotspot.setAttribute("aria-expanded", "true");
    ubicarFicha(ficha, hotspot, contenedor);

    const fila = look ? $(`[data-fila="${id}"]`, look) : null;
    if (fila) fila.dataset.activa = "1";
  }

  /* --- Un solo listener de clic para todo -------------------------------- */
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-abrir-carrito]")) {
      e.preventDefault();
      abrirCajon();
      return;
    }

    if (e.target.closest("[data-cerrar-carrito]") || e.target === velo) {
      cerrarCajon();
      return;
    }

    const cantidad = e.target.closest("[data-cantidad]");
    if (cantidad) {
      const datos = new FormData();
      datos.append("clave", cantidad.dataset.cantidad);
      datos.append("cantidad", cantidad.dataset.valor);
      accionCarrito(URLS.actualizar, datos);
      return;
    }

    const quitar = e.target.closest("[data-quitar]");
    if (quitar) {
      const datos = new FormData();
      datos.append("clave", quitar.dataset.quitar);
      accionCarrito(URLS.quitar, datos);
      return;
    }

    const hotspot = e.target.closest(".hotspot");
    if (hotspot) {
      e.preventDefault();
      abrirFicha(hotspot);
      return;
    }

    if (e.target.closest("[data-cerrar-ficha]")) {
      cerrarFichas();
      return;
    }

    // Elegir talle dentro de la ficha del hotspot.
    const talle = e.target.closest(".ficha .talle");
    if (talle && !talle.disabled) {
      const ficha = talle.closest("[data-ficha]");
      $$(".talle", ficha).forEach((t) => t.setAttribute("aria-pressed", "false"));
      talle.setAttribute("aria-pressed", "true");
      const agregar = $("[data-ficha-agregar]", ficha);
      agregar.disabled = false;
      agregar.dataset.talle = talle.dataset.talle;
      agregar.textContent = "Agregar al carrito";
      return;
    }

    const agregarFicha = e.target.closest("[data-ficha-agregar]");
    if (agregarFicha && !agregarFicha.disabled) {
      const datos = new FormData();
      datos.append("producto", agregarFicha.dataset.producto);
      if (agregarFicha.dataset.talle) datos.append("talle", agregarFicha.dataset.talle);
      accionCarrito(URLS.agregar, datos);
      cerrarFichas();
      avisar("Agregamos la prenda al carrito.");
      return;
    }

    // Clic en cualquier otro lado: se cierra la ficha abierta.
    if (!e.target.closest("[data-ficha]")) cerrarFichas();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (cajon && cajon.dataset.abierto) cerrarCajon();
    cerrarFichas();
  });

  // Si cambia el ancho, la ficha abierta queda mal ubicada.
  window.addEventListener("resize", cerrarFichas, { passive: true });

  /* --- Filtro de categorías --------------------------------------------- */
  // En el cliente porque son ~20 prendas: recargar la página entera para
  // esconder 15 cards sería peor experiencia que filtrarlas acá.
  const filtros = $$("[data-filtro]");
  filtros.forEach((btn) => {
    btn.addEventListener("click", () => {
      const cat = btn.dataset.filtro;
      filtros.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      $$(".card").forEach((card) => {
        card.hidden = cat !== "todas" && card.dataset.categoria !== cat;
      });
    });
  });

  /* --- Selector de talle en la página de producto ------------------------ */
  const tallesProducto = $("[data-talles-producto]");
  if (tallesProducto) {
    const oculto = $("[data-talle-elegido]");
    const boton = $("[data-agregar-producto]");
    $$(".talle", tallesProducto).forEach((btn) => {
      if (btn.disabled) return;
      btn.addEventListener("click", () => {
        $$(".talle", tallesProducto).forEach((b) => b.setAttribute("aria-pressed", "false"));
        btn.setAttribute("aria-pressed", "true");
        if (oculto) oculto.value = btn.dataset.talle;
        if (boton) {
          boton.disabled = false;
          boton.textContent = "Agregar al carrito";
        }
      });
    });
  }

  sincronizarContador();
})();
