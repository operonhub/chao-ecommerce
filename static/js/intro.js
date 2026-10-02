/* ==========================================================================
   CHAO Indumentaria — intro de marca de la home
   --------------------------------------------------------------------------
   La entrada (disco, letras, frase) es CSS puro. Acá se maneja la salida:
   el disco "vuela" hasta el logo del header mientras el telón se abre, y
   cuando termina se saca la intro del DOM. Se ve una vez por sesión.

   Red de seguridad: si este archivo no carga, la animación CSS `intro-fin`
   oculta la intro sola a los pocos segundos.
   ========================================================================== */

(() => {
  "use strict";

  const intro = document.querySelector("[data-intro]");
  const raiz = document.documentElement;
  if (!intro) return;

  if (raiz.classList.contains("sin-intro")) {
    intro.remove();
    return;
  }

  try {
    sessionStorage.setItem("chao-intro", "1");
  } catch (e) {
    /* modo privado: se vuelve a ver, no pasa nada */
  }

  // Desde acá manda el JS: se apaga el fallback CSS.
  intro.classList.add("intro--js");

  const disco = intro.querySelector("[data-intro-disco]");
  const SALIDA_MS = 2350; // cuando arranca a abrirse el telón
  const APERTURA_MS = 1050;
  let terminada = false;
  let timerSalida = null;

  function terminar() {
    if (terminada) return;
    terminada = true;
    raiz.classList.remove("intro-activa");
    intro.remove();
    window.removeEventListener("keydown", saltarConTecla, true);
  }

  // Vuelo del disco al logo del header (FLIP): se mide dónde está el disco
  // del header y se traslada/escala el de la intro hasta quedar encima.
  function volarDisco() {
    const destino = document.querySelector(".barra .marca__disco");
    if (!disco || !destino || !disco.animate) return;
    const a = disco.getBoundingClientRect();
    const b = destino.getBoundingClientRect();
    if (!a.width || !b.width) return;
    const dx = b.left + b.width / 2 - (a.left + a.width / 2);
    const dy = b.top + b.height / 2 - (a.top + a.height / 2);
    const escala = b.width / a.width;
    disco.animate(
      [
        { transform: "translate(0, 0) scale(1)" },
        { transform: `translate(${dx}px, ${dy}px) scale(${escala})` },
      ],
      { duration: 900, easing: "cubic-bezier(0.7, 0, 0.2, 1)", fill: "forwards" }
    );
  }

  function salir() {
    intro.classList.add("intro--saliendo");
    volarDisco();
    window.setTimeout(terminar, APERTURA_MS);
  }

  // Saltar: un toque, Enter, Espacio o Escape. Se abre más rápido y el hero
  // entra sin esperar.
  function saltar() {
    if (terminada || intro.classList.contains("intro--saltando")) return;
    window.clearTimeout(timerSalida);
    raiz.classList.add("intro-saltada");
    intro.classList.add("intro--saltando");
    window.setTimeout(terminar, 450);
  }

  function saltarConTecla(e) {
    // Durante la intro, ninguna tecla mueve las diapositivas de atrás.
    e.stopImmediatePropagation();
    if (["Enter", " ", "Escape", "ArrowRight"].includes(e.key)) {
      e.preventDefault();
      saltar();
    }
  }

  intro.addEventListener("click", saltar);
  window.addEventListener("keydown", saltarConTecla, true);

  // El CSS arrancó a animar cuando se pintó la intro (el script inline del
  // template anota ese momento); este archivo carga un poco después, así que
  // se descuenta lo que ya pasó para que la salida no llegue tarde.
  const t0 = window.__chaoIntroT0 || performance.now();
  timerSalida = window.setTimeout(salir, Math.max(0, SALIDA_MS - (performance.now() - t0)));
})();
