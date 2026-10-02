/* ==========================================================================
   Mi tienda — JS del panel
   --------------------------------------------------------------------------
   Todo lo que hace es mandar una acción chica al servidor (fetch POST) y
   reflejar la respuesta. La verdad está en la base: si algo falla, se avisa y
   se deja la pantalla como estaba.
   ========================================================================== */

(() => {
  "use strict";

  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));

  const csrf = () => {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const campo = $('input[name="csrfmiddlewaretoken"]');
    return campo ? campo.value : "";
  };

  async function postear(url, datos) {
    const body = new FormData();
    Object.entries(datos).forEach(([k, v]) => body.append(k, v));
    const res = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body,
    });
    let json = {};
    try {
      json = await res.json();
    } catch {
      /* respuesta sin JSON */
    }
    if (!res.ok || json.ok === false) throw new Error(json.error || "No se pudo guardar. Probá de nuevo.");
    return json;
  }

  /* --- Toast --------------------------------------------------------------- */
  const toastEl = $("[data-toast]");
  let toastTimer;
  function toast(texto, tipo = "ok") {
    if (!toastEl) return;
    toastEl.textContent = texto;
    toastEl.dataset.tipo = tipo;
    toastEl.dataset.visible = "1";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => delete toastEl.dataset.visible, 2400);
  }

  const pesos = (n) => Math.round(n).toLocaleString("es-AR");

  /* --- Prendas: interruptores en la tarjeta --------------------------------- */
  const ETIQUETAS_TOGGLE = {
    activo: ["Visible en la tienda", "Oculta de la tienda"],
    destacado: ["Marcada como destacada", "Ya no es destacada"],
    precio_a_confirmar: ["Precio marcado como estimado", "Precio confirmado"],
  };

  document.addEventListener("click", async (e) => {
    const sw = e.target.closest("[data-toggle-campo]");
    if (!sw) return;
    const card = sw.closest("[data-prenda]");
    const campo = sw.dataset.toggleCampo;
    sw.dataset.cargando = "";
    try {
      const { valor } = await postear(card.dataset.urlToggle, { campo });
      sw.setAttribute("aria-pressed", String(valor));
      if (campo === "activo") card.classList.toggle("g-prenda--oculta", !valor);
      const [si, no] = ETIQUETAS_TOGGLE[campo] || ["Guardado", "Guardado"];
      toast(valor ? si : no);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      delete sw.dataset.cargando;
    }
  });

  /* --- Prendas: precio editable en la tarjeta -------------------------------- */
  $$("[data-precio-input]").forEach((input) => {
    let original = input.value;
    const caja = input.closest(".g-precio");
    const card = input.closest("[data-prenda]");

    input.addEventListener("focus", () => {
      original = input.value;
      input.select();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") {
        input.value = original;
        input.blur();
      }
    });
    input.addEventListener("input", () => {
      input.value = input.value.replace(/[^\d.]/g, "");
    });
    input.addEventListener("blur", async () => {
      if (input.value === original) return;
      delete caja.dataset.error;
      try {
        const { precio } = await postear(card.dataset.urlPrecio, { precio: input.value });
        input.value = pesos(precio);
        original = input.value;
        caja.dataset.guardado = "1";
        setTimeout(() => delete caja.dataset.guardado, 1600);
        // Escribirlo a mano lo confirma: el servidor apaga "precio a confirmar".
        const conf = $('[data-toggle-campo="precio_a_confirmar"]', card);
        if (conf) conf.setAttribute("aria-pressed", "false");
        toast("Precio actualizado en la tienda");
      } catch (err) {
        caja.dataset.error = "1";
        input.value = original;
        toast(err.message, "error");
      }
    });
  });

  /* --- Ficha: fotos ----------------------------------------------------------- */
  const grillaFotos = $("[data-fotos]");
  if (grillaFotos) {
    grillaFotos.addEventListener("click", async (e) => {
      const mover = e.target.closest("[data-foto-accion]");
      const borrar = e.target.closest("[data-foto-borrar]");
      const fig = e.target.closest("[data-foto]");
      if (!fig || (!mover && !borrar)) return;

      if (borrar) {
        if (!confirm("¿Borrar esta foto?")) return;
        fig.dataset.cargando = "";
        try {
          await postear(fig.dataset.urlBorrar, {});
          fig.remove();
          toast("Foto borrada");
        } catch (err) {
          delete fig.dataset.cargando;
          toast(err.message, "error");
        }
        return;
      }

      fig.dataset.cargando = "";
      try {
        const { orden } = await postear(fig.dataset.urlMover, { dir: mover.dataset.fotoAccion });
        const subir = $(".g-subir", grillaFotos);
        orden.forEach((id) => {
          const nodo = $(`[data-foto="${id}"]`, grillaFotos);
          if (nodo) grillaFotos.insertBefore(nodo, subir);
        });
        if (mover.dataset.fotoAccion === "principal") toast("Ahora es la foto principal");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        delete fig.dataset.cargando;
      }
    });
  }

  const inputFotos = $("[data-fotos-input]");
  if (inputFotos) {
    const caja = $("[data-fotos-preview]");
    const grilla = $("[data-fotos-preview-grilla]");
    inputFotos.addEventListener("change", () => {
      grilla.replaceChildren(
        ...Array.from(inputFotos.files).map((f) => {
          const img = document.createElement("img");
          img.src = URL.createObjectURL(f);
          img.alt = f.name;
          return img;
        })
      );
      caja.hidden = inputFotos.files.length === 0;
    });
  }

  /* --- Ficha: etiquetas sugeridas ---------------------------------------------- */
  const inputEtiqueta = $("[data-etiqueta-input]");
  if (inputEtiqueta) {
    const marcar = () =>
      $$("[data-etiqueta]").forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.etiqueta === inputEtiqueta.value && b.dataset.etiqueta !== ""))
      );
    $$("[data-etiqueta]").forEach((b) =>
      b.addEventListener("click", () => {
        inputEtiqueta.value = b.dataset.etiqueta;
        inputEtiqueta.dispatchEvent(new Event("input", { bubbles: true }));
        marcar();
      })
    );
    inputEtiqueta.addEventListener("input", marcar);
    marcar();
  }

  /* --- Ficha: talles (marca los que tienen valor) ------------------------------ */
  $$("[data-stock-input]").forEach((input) => {
    const caja = input.closest(".g-talle");
    const pintar = () => caja.classList.toggle("g-talle--on", input.value.trim() !== "");
    input.addEventListener("input", pintar);
  });

  /* --- Ficha: avisar si se va sin guardar -------------------------------------- */
  const formPrenda = $("#form-prenda");
  if (formPrenda) {
    let sucio = false;
    formPrenda.addEventListener("input", () => (sucio = true));
    formPrenda.addEventListener("change", () => (sucio = true));
    formPrenda.addEventListener("submit", () => (sucio = false));
    window.addEventListener("beforeunload", (e) => {
      if (!sucio) return;
      e.preventDefault();
      e.returnValue = "";
    });
  }

  /* --- Pedidos ----------------------------------------------------------------- */
  $$("[data-pedido]").forEach((card) => {
    const url = card.dataset.url;
    const badge = $("[data-estado-badge]", card);
    const select = $("[data-pedido-estado]", card);
    const entregado = $("[data-pedido-entregado]", card);

    select?.addEventListener("change", async () => {
      const anterior = badge.className;
      try {
        const { estado } = await postear(url, { estado: select.value });
        badge.className = `g-estado g-estado--${estado}`;
        badge.textContent = select.options[select.selectedIndex].text;
        toast("Estado del pedido actualizado");
      } catch (err) {
        badge.className = anterior;
        toast(err.message, "error");
      }
    });

    entregado?.addEventListener("click", async () => {
      const nuevo = entregado.getAttribute("aria-pressed") !== "true";
      entregado.dataset.cargando = "";
      try {
        const res = await postear(url, { entregado: nuevo ? "1" : "0" });
        entregado.setAttribute("aria-pressed", String(res.entregado));
        card.classList.toggle("g-pedido--entregado", res.entregado);
        toast(res.entregado ? "Marcado como entregado" : "Marcado como no entregado");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        delete entregado.dataset.cargando;
      }
    });
  });

  /* --- Confirmaciones ---------------------------------------------------------- */
  $$("form[data-confirmar]").forEach((f) =>
    f.addEventListener("submit", (e) => {
      if (!confirm(f.dataset.confirmar)) e.preventDefault();
    })
  );

  /* --- Portada: vista previa en vivo ------------------------------------------- */
  const portada = $("[data-portada]");
  if (portada) {
    $$("[data-preview]", portada).forEach((input) => {
      const salida = $(`[data-preview-out="${input.dataset.preview}"]`, portada);
      input.addEventListener("input", () => {
        if (salida) salida.textContent = input.value;
      });
    });
    const foto = $("[data-preview-out-foto]", portada);
    $$("[data-preview-foto]", portada).forEach((radio) =>
      radio.addEventListener("change", () => {
        if (radio.checked && foto) foto.src = radio.dataset.previewFoto;
      })
    );
  }
})();
