/* ==========================================================================
   CHAO — checkout
   Muestra la dirección solo si es envío, deja "efectivo" solo para retiro y
   recalcula el resumen en vivo. Es solo para que se vea claro: el servidor
   vuelve a validar todo y calcula el monto que se cobra.
   ========================================================================== */

(() => {
  "use strict";

  const form = document.querySelector("[data-checkout]");
  if (!form) return;

  const pesos = (n) => "$" + Math.round(n).toLocaleString("es-AR");
  const subtotal = parseFloat(form.dataset.subtotal) || 0;
  const pctTransferencia = parseFloat(form.dataset.descuentoTransferencia) || 0;

  const direccion = form.querySelector("[data-direccion]");
  const notaCoordinar = form.querySelector("[data-nota-coordinar]");
  const efectivo = form.querySelector("[data-solo-retiro]");
  const detalleEfectivo = form.querySelector("[data-detalle-efectivo]");
  const boton = form.querySelector("[data-boton-enviar]");
  const $ = (s) => document.querySelector(s);

  function elegido(nombre) {
    return form.querySelector(`input[name="${nombre}"]:checked`);
  }

  function pintar() {
    const entrega = elegido("entrega");
    const esEnvio = entrega && entrega.dataset.tipo === "envio";
    const costoTxt = entrega ? entrega.dataset.costo : "0";
    const aCoordinar = esEnvio && costoTxt === "";
    const costo = aCoordinar ? 0 : parseFloat(costoTxt) || 0;

    if (direccion) direccion.hidden = !esEnvio;
    if (notaCoordinar) notaCoordinar.hidden = !aCoordinar;

    // Efectivo es pagar en el mostrador: con envío no tiene sentido.
    if (efectivo) {
      const radio = efectivo.querySelector("input");
      radio.disabled = esEnvio;
      efectivo.classList.toggle("opcion--apagada", esEnvio);
      if (detalleEfectivo) {
        detalleEfectivo.textContent = esEnvio
          ? "Solo para retirar en el local."
          : "Te lo separamos y pagás cuando pasás por el local.";
      }
      if (esEnvio && radio.checked) {
        radio.checked = false;
        const otro = form.querySelector('input[name="metodo_pago"]:not(:disabled)');
        if (otro) otro.checked = true;
      }
    }

    const metodo = elegido("metodo_pago");
    const valorMetodo = metodo ? metodo.value : "";
    const descuento = valorMetodo === "transferencia" ? Math.round((subtotal * pctTransferencia) / 100) : 0;

    const lineaDescuento = $("[data-linea-descuento]");
    if (lineaDescuento) {
      lineaDescuento.hidden = !descuento;
      $("[data-descuento]").textContent = "−" + pesos(descuento);
    }
    $("[data-envio-nombre]").textContent = entrega ? entrega.dataset.nombre : "Envío";
    $("[data-envio]").textContent = !esEnvio ? "Gratis" : aCoordinar ? "A coordinar" : costo === 0 ? "Gratis" : pesos(costo);
    const total = pesos(subtotal - descuento + costo) + (aCoordinar ? " + envío" : "");
    $("[data-total]").textContent = pesos(subtotal - descuento + costo);
    const totalMovil = $("[data-total-movil]");
    if (totalMovil) totalMovil.textContent = total;
    $("[data-total-nota]").hidden = !aCoordinar;

    if (boton && !boton.disabled) {
      boton.firstChild.textContent =
        valorMetodo === "mercadopago"
          ? "Continuar al pago "
          : valorMetodo === "efectivo"
            ? "Reservar mi pedido "
            : "Confirmar pedido ";
    }
  }

  form.addEventListener("change", pintar);
  pintar();

  // Un solo envío: que un doble toque no cree dos pedidos.
  form.addEventListener("submit", () => {
    if (boton) {
      window.setTimeout(() => {
        boton.disabled = true;
        boton.classList.add("btn--cargando");
      }, 0);
    }
  });

  // Si el servidor devolvió errores, se lleva la vista al primero.
  const primerError = form.querySelector(".campo--error input, .campo--error select");
  if (primerError) primerError.focus({ preventScroll: false });
})();
