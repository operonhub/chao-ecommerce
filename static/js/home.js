/* ==========================================================================
   CHAO Indumentaria — home editorial
   --------------------------------------------------------------------------
   · Portada: el tríptico rota los looks con una persiana en ola, con barra de
     progreso tipo historias; se pausa si la portada no se ve o la pestaña está
     oculta. El scroll mueve los paneles a distinta velocidad (--p).
   · Header transparente mientras está sobre la portada.
   · Revelado de secciones al aparecer, frase que se ilumina palabra por
     palabra, parallax suave de fotos e índice lateral de secciones.
   Todo es mejora progresiva: sin este archivo la página se ve completa.
   ========================================================================== */

(() => {
  "use strict";

  const quieto = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const raiz = document.documentElement;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  if (!quieto) raiz.classList.add("revela");

  /* --- Partir texto en palabras (titular y frase) ------------------------- */
  function partir(el, conInterior) {
    let n = 0;
    const recorrer = (nodo) => {
      Array.from(nodo.childNodes).forEach((hijo) => {
        if (hijo.nodeType === Node.TEXT_NODE) {
          const frag = document.createDocumentFragment();
          hijo.textContent.split(/(\s+)/).forEach((trozo) => {
            if (!trozo) return;
            if (/^\s+$/.test(trozo)) {
              frag.appendChild(document.createTextNode(trozo));
              return;
            }
            const palabra = document.createElement("span");
            palabra.className = "palabra";
            if (conInterior) {
              const dentro = document.createElement("span");
              dentro.style.setProperty("--n", n);
              dentro.textContent = trozo;
              palabra.appendChild(dentro);
            } else {
              palabra.textContent = trozo;
            }
            n += 1;
            frag.appendChild(palabra);
          });
          hijo.replaceWith(frag);
        } else if (hijo.nodeType === Node.ELEMENT_NODE) {
          recorrer(hijo);
        }
      });
    };
    recorrer(el);
    return $$(".palabra", el);
  }

  /* --- Portada ------------------------------------------------------------- */
  const portada = $("[data-portada]");
  const barra = $(".barra");

  if (portada) {
    const titulo = $("[data-partir]", portada);
    if (titulo && !quieto) {
      partir(titulo, true);
      titulo.classList.add("partido");
    }

    let looks = [];
    try {
      looks = JSON.parse($("#looks-hero")?.textContent || "[]");
    } catch (e) {
      looks = [];
    }

    const paneles = $$("[data-panel]", portada);
    const progreso = $("[data-progreso]", portada);
    const DURACION = 6500;
    const visibles = () => paneles.filter((p) => p.offsetParent !== null).length || 1;

    let paso = 0;
    let timer = null;
    let restante = DURACION;
    let inicio = 0;
    let enPantalla = true;
    let botones = [];

    // Precarga: que la persiana no descubra una foto a medio bajar.
    looks.forEach((l) => {
      const img = new Image();
      img.src = l.src;
    });

    function pasos() {
      return Math.max(1, Math.ceil(looks.length / visibles()));
    }

    function armarProgreso() {
      if (!progreso) return;
      progreso.innerHTML = "";
      progreso.style.setProperty("--duracion", `${DURACION}ms`);
      botones = Array.from({ length: pasos() }, (_, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.setAttribute("aria-label", `Ver grupo de looks ${i + 1}`);
        b.addEventListener("click", () => ir(i));
        progreso.appendChild(b);
        return b;
      });
      progreso.hidden = botones.length < 2;
      pintarProgreso();
    }

    function pintarProgreso() {
      botones.forEach((b, i) => {
        b.classList.remove("activo");
        b.classList.toggle("visto", i < paso);
      });
      const actual = botones[paso];
      if (actual) {
        void actual.offsetWidth; // reinicia la animación de la barra
        actual.classList.add("activo");
      }
    }

    function mostrar(nuevoPaso) {
      const v = visibles();
      paneles.slice(0, v).forEach((panel, i) => {
        const look = looks[(nuevoPaso * v + i) % looks.length];
        if (!look) return;
        const mueve = $(".portada__mueve", panel);
        const capas = $$(".portada__capa", mueve);
        const capa = document.createElement("div");
        capa.className = "portada__capa entrando";
        capa.style.setProperty("--retraso", `${i * 0.16}s`);
        const img = document.createElement("img");
        img.src = look.src;
        img.alt = look.alt;
        capa.appendChild(img);
        mueve.appendChild(capa);
        capa.addEventListener(
          "animationend",
          (e) => {
            if (e.target !== capa) return;
            capa.classList.remove("entrando");
            capas.forEach((c) => c.remove());
          },
          { once: false }
        );

        const nombre = $("[data-nombre]", panel);
        if (nombre) {
          nombre.classList.add("cambiando");
          window.setTimeout(() => {
            nombre.textContent = look.nombre;
            nombre.href = look.href;
            nombre.classList.remove("cambiando");
          }, 380 + i * 160);
        }
      });
      paso = nuevoPaso;
      pintarProgreso();
    }

    function programar(ms = DURACION) {
      window.clearTimeout(timer);
      restante = ms;
      inicio = performance.now();
      timer = window.setTimeout(() => {
        mostrar((paso + 1) % pasos());
        programar();
      }, ms);
    }

    function pausar() {
      if (!timer) return;
      window.clearTimeout(timer);
      timer = null;
      restante = Math.max(400, restante - (performance.now() - inicio));
      portada.classList.add("pausada");
    }

    function seguir() {
      if (timer || !enPantalla || document.hidden) return;
      portada.classList.remove("pausada");
      programar(restante);
    }

    function ir(i) {
      if (i === paso) return;
      mostrar(i);
      programar();
    }

    if (looks.length > visibles() && !quieto) {
      armarProgreso();
      // La primera rotación espera a que termine la entrada de la portada.
      const espera = raiz.classList.contains("intro-activa") ? 2600 : 300;
      window.setTimeout(() => programar(), espera);

      new IntersectionObserver(([e]) => {
        enPantalla = e.isIntersecting;
        enPantalla ? seguir() : pausar();
      }).observe(portada);

      document.addEventListener("visibilitychange", () => (document.hidden ? pausar() : seguir()));

      // Si cambia de celular (1 panel) a desktop (3), se reacomoda el progreso.
      let anchoAntes = innerWidth > 900;
      window.addEventListener("resize", () => {
        const ahora = innerWidth > 900;
        if (ahora === anchoAntes) return;
        anchoAntes = ahora;
        paso = 0;
        armarProgreso();
        programar();
      });
    } else if (progreso) {
      progreso.hidden = true;
    }
  }

  /* --- Scroll: progreso de la portada, header, parallax, frase ------------ */
  const parallax = $$("[data-parallax]");
  const frase = $("[data-frase]");
  const palabrasFrase = frase && !quieto ? partir(frase, false) : [];
  let pendiente = false;

  function enScroll() {
    pendiente = false;
    const alto = innerHeight;

    if (portada) {
      const h = portada.offsetHeight;
      const p = Math.min(1, Math.max(0, scrollY / h));
      if (!quieto) portada.style.setProperty("--p", p.toFixed(4));
      const altoBarra = barra ? barra.offsetHeight : 64;
      barra?.classList.toggle("sobre-portada", scrollY < h - altoBarra - 4);
    }

    if (!quieto) {
      parallax.forEach((img) => {
        const marco = img.parentElement.getBoundingClientRect();
        if (marco.bottom < 0 || marco.top > alto) return;
        // -1 cuando el marco entra por abajo, +1 cuando sale por arriba.
        const t = (marco.top + marco.height / 2 - alto / 2) / (alto / 2 + marco.height / 2);
        img.style.setProperty("--y", `${(t * -6).toFixed(2)}%`);
      });
    }

    if (palabrasFrase.length) {
      const r = frase.getBoundingClientRect();
      // Se prende de a una entre que la frase entra al 85% de la pantalla y
      // llega al 35%: se termina de leer justo cuando está en el centro.
      const t = (alto * 0.85 - r.top) / (alto * 0.5 + r.height * 0.6);
      const prendidas = Math.round(Math.min(1, Math.max(0, t)) * palabrasFrase.length);
      palabrasFrase.forEach((w, i) => w.classList.toggle("prendida", i < prendidas));
    }
  }

  function pedirFrame() {
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(enScroll);
  }

  window.addEventListener("scroll", pedirFrame, { passive: true });
  window.addEventListener("resize", pedirFrame);
  enScroll();

  /* --- Revelado de secciones ------------------------------------------------ */
  $$("[data-revelar-grupo]").forEach((g) =>
    Array.from(g.children).forEach((hijo, i) => hijo.style.setProperty("--n", i % 6))
  );

  const revelables = $$("[data-revelar], [data-revelar-grupo]");
  if (quieto || !("IntersectionObserver" in window)) {
    revelables.forEach((el) => el.classList.add("revelado"));
  } else {
    const obs = new IntersectionObserver(
      (entradas) => {
        entradas.forEach((e) => {
          if (!e.isIntersecting) return;
          e.target.classList.add("revelado");
          obs.unobserve(e.target);
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 }
    );
    revelables.forEach((el) => obs.observe(el));
  }

  /* --- Índice lateral ------------------------------------------------------- */
  const indice = $("[data-indice]");
  const secciones = $$("[data-seccion]");
  if (indice && secciones.length > 2) {
    const links = secciones.map((s) => {
      if (!s.id) s.id = `seccion-${s.dataset.seccion.toLowerCase().replace(/\W+/g, "-")}`;
      const a = document.createElement("a");
      a.href = `#${s.id}`;
      a.innerHTML = `<span>${s.dataset.seccion}</span>`;
      a.setAttribute("aria-label", s.dataset.seccion);
      indice.appendChild(a);
      return a;
    });

    const marcar = new IntersectionObserver(
      (entradas) => {
        entradas.forEach((e) => {
          if (!e.isIntersecting) return;
          const i = secciones.indexOf(e.target);
          links.forEach((a, j) => a.classList.toggle("activo", j === i));
        });
      },
      { rootMargin: "-45% 0px -50% 0px" }
    );
    secciones.forEach((s) => marcar.observe(s));
    window.setTimeout(() => indice.classList.add("listo"), raiz.classList.contains("intro-activa") ? 3200 : 400);
  }
})();
