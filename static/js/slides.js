/* ==========================================================================
   CHAO Indumentaria — motor de diapositivas de la home
   --------------------------------------------------------------------------
   Puerto a JS plano de la mecánica de cortina del mockup de Claude Design
   (que ahí vivía en React). Sin dependencias: cambia qué <section class="slide">
   tiene la clase "activa" mientras una cortina de tela cubre la pantalla.

   Cortina cubre → se cambia la diapositiva activa (instantáneo, tapado) →
   cortina descubre del lado contrario. Nunca hay dos animaciones de layout
   compitiendo: mientras la cortina está en pantalla no hay transición de
   opacidad en las diapositivas, es un corte seco por debajo de la tela.
   ========================================================================== */

(() => {
  "use strict";

  const stage = document.querySelector("[data-stage]");
  if (!stage) return; // No es la home: este script no hace nada.

  const cortina = stage.querySelector("[data-cortina]");
  const slides = Array.from(stage.querySelectorAll(".slide"));
  const nombres = slides.map((s) => s.dataset.slide);
  const total = slides.length;

  const btnPrev = stage.querySelector("[data-slide-prev]");
  const btnNext = stage.querySelector("[data-slide-next]");
  const puntosWrap = stage.querySelector("[data-slide-puntos]");
  const contador = stage.querySelector("[data-slide-actual]");
  const nombreActual = stage.querySelector("[data-slide-nombre]");

  const COVER_MS = 720;
  const HOLD_MS = 60;

  let idx = Math.max(0, slides.findIndex((s) => s.classList.contains("activa")));
  if (idx < 0) idx = 0;
  let animando = false;

  // Puntos del indicador, uno por diapositiva.
  const puntos = nombres.map((_, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "slide-punto" + (i === idx ? " activo" : "");
    b.setAttribute("aria-label", `Ir a la diapositiva ${i + 1}`);
    b.addEventListener("click", () => ir(i));
    puntosWrap?.appendChild(b);
    return b;
  });

  function pintar() {
    slides.forEach((s, i) => s.classList.toggle("activa", i === idx));
    puntos.forEach((p, i) => p.classList.toggle("activo", i === idx));
    if (contador) contador.textContent = String(idx + 1).padStart(2, "0");
    if (nombreActual) nombreActual.textContent = slides[idx].dataset.titulo || "";
    if (btnPrev) btnPrev.disabled = idx === 0;
    if (btnNext) btnNext.disabled = idx === total - 1;
    stage.classList.toggle("con-fondo-oscuro", slides[idx].dataset.oscura === "1");
    history.replaceState(null, "", idx === 0 ? location.pathname : `#${nombres[idx]}`);
  }

  function ir(destino, { instantaneo = false } = {}) {
    if (destino === idx || destino < 0 || destino >= total || animando) return;
    const dir = destino > idx ? "next" : "prev";
    // Después del primer cambio, el hero ya no espera a que termine la intro
    // para animar su entrada (ver --base-entrada en chao.css).
    stage.classList.add("navegado");

    if (instantaneo || !cortina) {
      idx = destino;
      pintar();
      return;
    }

    animando = true;
    // La cortina entra desde el lado hacia el que "avanza" la lectura.
    cortina.className = "cortina " + (dir === "next" ? "desde-derecha" : "desde-izquierda");
    // Fuerza reflow para que el navegador registre la posición inicial antes
    // de animar — si no, a veces "cubriendo" arranca ya en el estado final.
    void cortina.offsetWidth;
    cortina.classList.add("cubriendo");

    window.setTimeout(() => {
      idx = destino;
      pintar();

      window.setTimeout(() => {
        cortina.className = "cortina " + (dir === "next" ? "sale-izquierda" : "sale-derecha");
        window.setTimeout(() => {
          animando = false;
        }, COVER_MS);
      }, HOLD_MS);
    }, COVER_MS);
  }

  function siguiente() {
    ir(idx + 1);
  }
  function anterior() {
    ir(idx - 1);
  }

  btnPrev?.addEventListener("click", anterior);
  btnNext?.addEventListener("click", siguiente);

  // Botones "Ver colección" / "Conocenos" del hero (y cualquier otro que
  // quiera saltar directo a una diapositiva por nombre).
  stage.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-ir-slide]");
    if (!btn) return;
    const destino = nombres.indexOf(btn.dataset.irSlide);
    if (destino >= 0) ir(destino);
  });

  document.addEventListener("keydown", (e) => {
    // Mientras está abierto el menú o la bolsa, las flechas son de ellos.
    if (document.querySelector("[data-abierto]")) return;
    if (e.target.closest?.("input, select, textarea")) return;
    if (e.key === "ArrowRight") siguiente();
    if (e.key === "ArrowLeft") anterior();
  });

  // Swipe táctil. El carrusel de prendas en el celular scrollea de costado
  // por su cuenta ([data-sin-swipe]): ahí deslizar no cambia de diapositiva.
  let touchX = null;
  stage.addEventListener(
    "touchstart",
    (e) => {
      touchX = e.target.closest("[data-sin-swipe]") ? null : e.touches[0].clientX;
    },
    { passive: true }
  );
  stage.addEventListener(
    "touchend",
    (e) => {
      if (touchX === null) return;
      const delta = e.changedTouches[0].clientX - touchX;
      touchX = null;
      if (Math.abs(delta) < 48) return;
      if (delta < 0) siguiente();
      else anterior();
    },
    { passive: true }
  );

  // Deep link: /#nosotras entra directo en esa diapositiva, sin cortina.
  const hash = location.hash.replace("#", "");
  const destinoInicial = nombres.indexOf(hash);
  if (destinoInicial >= 0) {
    stage.classList.add("navegado");
    ir(destinoInicial, { instantaneo: true });
  }

  // Ya estando en la home, los links del menú a "/#contacto" solo cambian el
  // hash (no recargan): se escucha el cambio y se va con cortina.
  window.addEventListener("hashchange", () => {
    const destino = nombres.indexOf(location.hash.replace("#", ""));
    if (destino >= 0) ir(destino);
  });

  pintar();
})();
