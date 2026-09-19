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
  const query = () => `company_id=${encodeURIComponent(context().company)}`;
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("sales").hidden = true;
  }

  function reset() {
    selected = null;
    hide();
    $("sales-quote-rows").replaceChildren();
    $("sales-order-rows").replaceChildren();
    $("sales-actions").replaceChildren();
    $("sales-revision-form").hidden = true;
    $("sales-convert-form").hidden = true;
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
        row.append(
          cell(order.number),
          cell(`Cotação ${order.source_quote_id.slice(0, 8)}`),
          state,
          cell(money(order.net_amount)),
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
