/* ==========================================================================
   CHAO — pago con el Payment Brick de Mercado Pago
   El formulario de tarjeta lo dibuja MP en un recuadro seguro. Al confirmar,
   se manda el token de la tarjeta a /procesar/ y el servidor crea la order
   (API de Orders de MP) con el monto del pedido. El botón "Mercado Pago" (billetera) redirige solo a MP.
   ========================================================================== */

(() => {
  "use strict";

  const datos = document.getElementById("mp-config");
  if (!datos || typeof window.MercadoPago !== "function") {
    mostrarError("No pudimos cargar el pago de Mercado Pago. Recargá la página o escribinos por WhatsApp.");
    return;
  }

  const cfg = JSON.parse(datos.textContent);
  const csrf = document.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
  const cargando = document.querySelector("[data-pago-cargando]");

  function mostrarError(texto) {
    const caja = document.querySelector("[data-pago-error]");
    if (!caja) return;
    caja.textContent = texto;
    caja.hidden = !texto;
  }

  const mp = new window.MercadoPago(cfg.publicKey, { locale: "es-AR" });

  const metodos = { creditCard: "all", debitCard: "all" };
  if (cfg.preferenceId) metodos.mercadoPago = "all";

  mp.bricks()
    .create("payment", "pago-brick", {
      initialization: {
        amount: cfg.monto,
        ...(cfg.preferenceId ? { preferenceId: cfg.preferenceId } : {}),
        payer: { email: cfg.email },
      },
      customization: {
        paymentMethods: metodos,
        visual: {
          style: {
            theme: "default",
            customVariables: {
              baseColor: "#241B16",
              textPrimaryColor: "#241B16",
              textSecondaryColor: "#4A3A30",
              formBackgroundColor: "#FAF6EE",
              inputBackgroundColor: "#FFFFFF",
              outlinePrimaryColor: "#2f6b70",
              buttonTextColor: "#FAF6EE",
              borderRadiusSmall: "2px",
              borderRadiusMedium: "4px",
              borderRadiusLarge: "4px",
              borderRadiusFull: "999px",
            },
          },
        },
      },
      callbacks: {
        onReady: () => {
          if (cargando) cargando.hidden = true;
        },
        onError: (error) => {
          console.error("Mercado Pago:", error);
          if (cargando) cargando.hidden = true;
          if (error && error.type === "critical") {
            mostrarError("El pago de Mercado Pago no está disponible ahora. Escribinos por WhatsApp y lo resolvemos.");
          }
        },
        onSubmit: ({ selectedPaymentMethod, formData }) => {
          mostrarError("");
          // Billetera de Mercado Pago: el Brick redirige solo a MP con la preferencia.
          if (selectedPaymentMethod === "wallet_purchase") return Promise.resolve();

          return fetch(cfg.urlProcesar, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            // La API de Orders necesita saber si es crédito o débito.
            body: JSON.stringify({ ...formData, payment_type_id: selectedPaymentMethod }),
          })
            .then((r) => r.json())
            .then((res) => {
              if (res.estado === "pagado" || res.estado === "pendiente") {
                window.location.href = res.url || cfg.urlPedido;
                return;
              }
              mostrarError(res.mensaje || "El pago no pasó. Probá con otra tarjeta.");
              throw new Error(res.estado);
            })
            .catch((err) => {
              if (!document.querySelector("[data-pago-error]")?.textContent) {
                mostrarError("No pudimos conectar con Mercado Pago. Probá de nuevo en un momento.");
              }
              throw err; // el Brick vuelve a habilitar el botón
            });
        },
      },
    })
    .catch((err) => {
      console.error(err);
      if (cargando) cargando.hidden = true;
      mostrarError("No pudimos cargar el pago de Mercado Pago. Recargá la página o escribinos por WhatsApp.");
    });
})();
