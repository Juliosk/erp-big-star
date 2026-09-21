const $ = (id) => document.getElementById(id);

const labels = {
  DRAFT: "Rascunho",
  SENT: "Enviada",
  ACCEPTED: "Aceita",
  PARTIALLY_ACCEPTED: "Aceita parcialmente",
  LOST: "Perdida",
  CONVERTED: "Convertida",
  APPROVED: "Aprovado",
  CANCELLED: "Cancelado",
  COMPLETED: "Concluído",
  HELD: "Reserva ativa",
  RELEASED: "Liberada",
  EXPIRED: "Expirada",
};

function money(value) {
  return Number(value || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value;
  return td;
}

function badge(value) {
  const span = document.createElement("span");
  span.className = `status ${value}`;
  span.textContent = labels[value] || value;
  return span;
}

export function mountSales({ api, context, notice, enter }) {
  let selected = null;
  let selectedOrder = null;
  let reservation = null;
  let holdTimer = null;
  const query = () => `company_id=${encodeURIComponent(context().company)}`;
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("sales").hidden = true;
    stopHoldClock();
  }

  function reset() {
    selected = null;
    selectedOrder = null;
    reservation = null;
    hide();
    $("sales-quote-rows").replaceChildren();
    $("sales-order-rows").replaceChildren();
    $("sales-actions").replaceChildren();
    $("sales-revision-form").hidden = true;
    $("sales-convert-form").hidden = true;
    $("sales-reservation-panel").hidden = true;
    stopHoldClock();
  }

  function stopHoldClock() {
    if (holdTimer) window.clearInterval(holdTimer);
    holdTimer = null;
  }

  function quantity(value) {
    return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 6 });
  }

  async function getReservation(orderId) {
    if (!can("sales.order.reserve")) return null;
    try {
      return await api(`sales/orders/${orderId}/reservation?${query()}`);
    } catch (error) {
      if (error.code === "RESOURCE_NOT_FOUND") return null;
      throw error;
    }
  }

  async function loadWarehouses() {
    const select = $("sales-warehouse");
    if (!can("inventory.warehouse.read")) {
      select.replaceChildren(new Option("Informe pelo cockpit de estoque", ""));
      return;
    }
    const result = await api(`inventory/warehouses?${query()}&active=true&page_size=100`);
    select.replaceChildren(
      new Option("Selecione", ""),
      ...result.data.map((item) => new Option(`${item.code} · ${item.name}`, item.id)),
    );
  }

  async function loadAvailability() {
    if (!selectedOrder || !can("inventory.availability.read")) {
      $("sales-available").textContent = "—";
      $("sales-available-meta").textContent = "Consulta de ATP não autorizada";
      return;
    }
    const warehouse = $("sales-warehouse").value;
    const totals = await Promise.all(selectedOrder.items.map(async (item) => {
      const params = `${query()}&product_id=${item.product_id}${warehouse ? `&warehouse_id=${warehouse}` : ""}&page_size=100`;
      const result = await api(`inventory/availability?${params}`);
      return result.data.reduce((sum, row) => sum + Number(row.available), 0);
    }));
    $("sales-available").textContent = totals.length === 1
      ? quantity(totals[0])
      : `${totals.length} SKUs`;
    $("sales-available-meta").textContent = totals.length === 1
      ? `ATP do produto ${selectedOrder.items[0].product_id.slice(0, 8)}`
      : totals.map((value, index) => `#${index + 1}: ${quantity(value)}`).join(" · ");
  }

  function renderHoldClock() {
    stopHoldClock();
    const until = reservation?.hold_expires_at;
    if (!until || reservation.status !== "HELD") {
      $("sales-hold-clock").textContent = reservation ? labels[reservation.status] : "—";
      $("sales-hold-until").textContent = until
        ? new Date(until).toLocaleString("pt-BR")
        : "Ainda não iniciado";
      return;
    }
    const tick = () => {
      const remaining = Math.max(0, new Date(until).getTime() - Date.now());
      const hours = Math.floor(remaining / 3_600_000);
      const minutes = Math.floor((remaining % 3_600_000) / 60_000);
      const seconds = Math.floor((remaining % 60_000) / 1000);
      $("sales-hold-clock").textContent = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
      if (!remaining) stopHoldClock();
    };
    $("sales-hold-until").textContent = `Até ${new Date(until).toLocaleString("pt-BR")}`;
    tick();
    holdTimer = window.setInterval(tick, 1000);
  }

  function renderReservation() {
    const signal = $("sales-reservation-status");
    signal.className = `reservation-signal ${reservation?.status || ""}`;
    signal.textContent = reservation ? labels[reservation.status] || reservation.status : "Sem reserva";
    $("sales-reserve-form").hidden = Boolean(reservation) || !can("sales.order.reserve") || selectedOrder.status !== "APPROVED";
    $("sales-reservation-lines").replaceChildren(
      ...(reservation?.lines || selectedOrder.items).map((item) => {
        const line = document.createElement("div");
        line.className = "reservation-line";
        line.append(
          Object.assign(document.createElement("span"), { textContent: `Produto ${item.product_id}` }),
          Object.assign(document.createElement("strong"), { textContent: `${quantity(item.quantity)} un.` }),
          Object.assign(document.createElement("span"), { textContent: reservation ? "Alocado no M5" : "Aguardando reserva" }),
        );
        return line;
      }),
    );
    const actions = $("sales-reservation-actions");
    actions.replaceChildren();
    if (reservation?.status === "HELD" && can("sales.order.reserve")) {
      actionInto(actions, "Estender hold +2h", extendHold);
    }
    if (reservation?.status === "HELD" && can("sales.order.cancel")) {
      actionInto(actions, "Cancelar pedido e liberar", cancelOrder, false);
    }
    renderHoldClock();
  }

  async function selectOrder(id) {
    selectedOrder = await api(`sales/orders/${id}?${query()}`);
    reservation = await getReservation(id);
    $("sales-reservation-panel").hidden = false;
    $("sales-order-title").textContent = selectedOrder.number;
    $("sales-order-meta").textContent = `${labels[selectedOrder.status] || selectedOrder.status} · versão ${selectedOrder.version} · ${selectedOrder.items.length} item(ns)`;
    $("sales-required").textContent = quantity(selectedOrder.items.reduce((sum, item) => sum + Number(item.quantity), 0));
    await loadWarehouses();
    renderReservation();
    await loadAvailability();
    $("sales-reservation-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function actionInto(container, label, handler, secondary = true) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (secondary) button.className = "secondary";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await handler(); } catch (error) { notice(error.message); button.disabled = false; }
    });
    container.append(button);
  }

  async function extendHold() {
    const expiresAt = new Date(Date.now() + 2 * 3_600_000).toISOString();
    reservation = await api(`sales/orders/${selectedOrder.id}/reservation/extend-hold`, {
      method: "POST", version: reservation.version, key: crypto.randomUUID(),
      body: { company_id: context().company, expires_at: expiresAt },
    });
    renderReservation();
    notice("Hold estendido por mais 2 horas.");
  }

  async function cancelOrder() {
    const result = await api(`sales/orders/${selectedOrder.id}/cancel?${query()}`, {
      method: "POST", version: selectedOrder.version, key: crypto.randomUUID(),
    });
    selectedOrder = result.order;
    reservation = result.reservation;
    renderReservation();
    await Promise.all([loadOrders(), loadAvailability()]);
    notice("Pedido cancelado e reserva física liberada.");
  }

  async function loadOrders() {
    if (!can("sales.order.read")) return;
    const result = await api(`sales/orders?${query()}&page=1&page_size=50`);
    $("sales-order-count").textContent = String(result.data.length);
    $("sales-order-rows").replaceChildren(
      ...result.data.map((order) => {
        const row = document.createElement("tr");
        const state = document.createElement("td");
        state.append(badge(order.status));
        const reservationCell = document.createElement("td");
        reservationCell.textContent = can("sales.order.reserve") ? "Abrir pedido" : "—";
        const actionCell = document.createElement("td");
        const open = document.createElement("button");
        open.type = "button";
        open.className = "quiet";
        open.textContent = "Gerir →";
        open.addEventListener("click", () => selectOrder(order.id).catch((error) => notice(error.message)));
        actionCell.append(open);
        row.append(
          cell(order.number),
          cell(`Cotação ${order.source_quote_id.slice(0, 8)}`),
          state,
          reservationCell,
          cell(money(order.net_amount)),
          actionCell,
        );
        return row;
      }),
    );
  }

  async function selectQuote(id) {
    selected = await api(`sales/quotes/${id}?${query()}`);
    const quote = selected.quote;
    const current = selected.revisions.at(-1);
    $("sales-selected-title").textContent = quote.number;
    $("sales-selected-meta").textContent =
      `${labels[quote.status] || quote.status} · versão ${quote.version} · cliente ${quote.customer_id}`;
    $("sales-revision-form").hidden =
      quote.status !== "DRAFT" || !can("sales.quote.update");
    $("sales-totals").hidden = !current;
    $("sales-totals").textContent = current
      ? `Bruto ${money(current.gross_amount)}  ·  Desconto ${money(current.discount_amount)}  ·  Líquido ${money(current.net_amount)}`
      : "";
    renderActions();
  }

  function action(label, handler, secondary = true) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (secondary) button.className = "secondary";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await handler();
      } catch (error) {
        notice(error.message);
        button.disabled = false;
      }
    });
    $("sales-actions").append(button);
  }

  function renderActions() {
    $("sales-actions").replaceChildren();
    $("sales-convert-form").hidden = true;
    if (!selected) return;
    const quote = selected.quote;
    if (quote.status === "DRAFT" && quote.current_revision_number > 0) {
      if (can("sales.discount.request") && selected.revisions.at(-1).discount_amount !== "0.00") {
        action("Solicitar aprovação de desconto", async () => {
          await api(`sales/quotes/${quote.id}/discount-approval`, {
            method: "POST",
            version: quote.version,
            body: { company_id: context().company },
          });
          notice("Aprovação de desconto solicitada.");
          await selectQuote(quote.id);
        });
      }
      if (can("sales.quote.send")) {
        action("Enviar cotação", async () => {
          await transition("send");
        }, false);
      }
    }
    if (quote.status === "SENT" && can("sales.quote.update")) {
      action("Aceitar", () => transition("accept"), false);
      action("Aceitar parcialmente", () => transition("accept-partially"));
      action("Marcar como perdida", () => transition("lost"));
    }
    if (["ACCEPTED", "PARTIALLY_ACCEPTED"].includes(quote.status) && can("sales.order.create")) {
      $("sales-convert-form").hidden = false;
    }
  }

  async function transition(name) {
    const quote = selected.quote;
    await api(`sales/quotes/${quote.id}/${name}`, {
      method: "POST",
      version: quote.version,
      body: { company_id: context().company },
    });
    await loadQuotes();
    await selectQuote(quote.id);
    notice("Situação da cotação atualizada.");
  }

  async function loadQuotes() {
    const result = await api(`sales/quotes?${query()}&page=1&page_size=50`);
    $("sales-quote-count").textContent = String(result.data.length);
    $("sales-empty").hidden = result.data.length > 0;
    $("sales-quote-rows").replaceChildren();
    for (const quote of result.data) {
      const row = document.createElement("tr");
      const state = document.createElement("td");
      state.append(badge(quote.status));
      const actionCell = document.createElement("td");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "quiet";
      open.textContent = "Abrir →";
      open.addEventListener("click", () => selectQuote(quote.id).catch((error) => notice(error.message)));
      actionCell.append(open);
      row.append(cell(quote.number), state, cell(`Rev. ${quote.current_revision_number}`), actionCell);
      $("sales-quote-rows").append(row);
    }
  }

  async function show() {
    enter();
    $("sales").hidden = false;
    $("sales-quote-form").hidden = !can("sales.quote.create");
    await Promise.all([loadQuotes(), loadOrders()]);
  }

  $("sales-refresh").addEventListener("click", () => show().catch((error) => notice(error.message)));
  $("sales-warehouse").addEventListener("change", () => loadAvailability().catch((error) => notice(error.message)));
  $("sales-reserve-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const hours = Number($("sales-hold-hours").value);
      reservation = await api(`sales/orders/${selectedOrder.id}/reserve`, {
        method: "POST", version: selectedOrder.version, key: crypto.randomUUID(),
        body: {
          company_id: context().company,
          warehouse_id: $("sales-warehouse").value,
          reservation_kind: $("sales-reservation-kind").value,
          expires_at: new Date(Date.now() + hours * 3_600_000).toISOString(),
        },
      });
      renderReservation();
      await Promise.all([loadOrders(), loadAvailability()]);
      notice("Reserva física confirmada no M5.");
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });
  $("sales-quote-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.submitter;
    button.disabled = true;
    try {
      const quote = await api("sales/quotes", {
        method: "POST",
        body: {
          company_id: context().company,
          number: $("sales-quote-number").value.trim(),
          customer_id: $("sales-customer-id").value.trim(),
        },
      });
      form.reset();
      await loadQuotes();
      await selectQuote(quote.id);
      notice("Cotação criada.");
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });
  $("sales-revision-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      await api(`sales/quotes/${selected.quote.id}/revisions`, {
        method: "POST",
        version: selected.quote.version,
        body: {
          company_id: context().company,
          lines: [{
            product_id: $("sales-product-id").value.trim(),
            quantity: $("sales-quantity").value,
            unit_price: $("sales-unit-price").value,
            discount_amount: $("sales-discount").value,
          }],
        },
      });
      await loadQuotes();
      await selectQuote(selected.quote.id);
      notice("Revisão comercial salva.");
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });
  $("sales-convert-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.submitter;
    button.disabled = true;
    try {
      const quote = selected.quote;
      await api(`sales/quotes/${quote.id}/convert-to-order`, {
        method: "POST",
        version: quote.version,
        key: crypto.randomUUID(),
        body: {
          company_id: context().company,
          order_number: $("sales-order-number").value.trim(),
        },
      });
      form.reset();
      await Promise.all([loadQuotes(), loadOrders()]);
      await selectQuote(quote.id);
      notice("Pedido criado a partir da cotação.");
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  return { hide, reset, show };
}
