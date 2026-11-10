const $ = (id) => document.getElementById(id);
let token = "";
let noticeTimer = 0;

const marketplaceLabel = {
  MERCADO_LIVRE: "Mercado Livre",
  SHOPEE: "Shopee",
  NUVEMSHOP: "Nuvemshop",
};
const statusLabel = {
  PENDING: "Pendente",
  PAID: "Pago",
  SHIPPED: "Enviado",
  CANCELLED: "Cancelado",
};

async function api(path) {
  const response = await fetch(`/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  let body = null;
  try { body = await response.json(); } catch { /* resposta sem JSON */ }
  if (!response.ok) {
    const error = new Error(body?.error?.message || "Não foi possível carregar o cockpit.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value));
}
function percent(value) {
  return `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(Number(value))}%`;
}
function dateTime(value) {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
function notify(message) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").classList.add("visible");
  noticeTimer = window.setTimeout(() => $("notice").classList.remove("visible"), 2800);
}
function textElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function renderChannels(channels) {
  $("channels").replaceChildren(...channels.map((channel) => {
    const card = document.createElement("article");
    card.className = `channel-card market-${channel.marketplace.toLowerCase().replace("_", "-")}`;
    const header = document.createElement("header");
    header.append(
      textElement("span", "channel-name", marketplaceLabel[channel.marketplace] || channel.marketplace),
      textElement("span", "channel-count", `${channel.order_count} pedido(s)`),
    );
    const total = textElement("strong", "channel-total", money(channel.sales_amount));
    const margin = textElement(
      "p",
      "channel-margin",
      channel.order_count === 0
        ? "Sem pedidos no período"
        : channel.margin_percent === null
        ? `${channel.margin_pending_orders} pedido(s) aguardando custo M9`
        : `Margem comercial ${percent(channel.margin_percent)} · ${money(channel.margin_amount)}`,
    );
    const states = document.createElement("div");
    states.className = "channel-states";
    states.append(
      textElement("span", "", `${channel.pending_count} pendentes`),
      textElement("span", "", `${channel.paid_count} pagos`),
      textElement("span", "", `${channel.shipped_count} enviados`),
      textElement("span", "", `${channel.cancelled_count} cancelados`),
    );
    card.append(header, total, margin, states);
    return card;
  }));
}

function renderOrders(orders) {
  $("orders-empty").hidden = orders.length > 0;
  $("order-count").textContent = `${orders.length} pedido(s) exibido(s)`;
  $("orders").replaceChildren(...orders.map((order) => {
    const row = document.createElement("tr");
    const values = [
      ["Canal / pedido", `${marketplaceLabel[order.marketplace] || order.marketplace} · ${order.external_order_id}`, "mono"],
      ["Status", statusLabel[order.status] || order.status, `pill ${order.status === "CANCELLED" ? "bad" : order.status === "PENDING" ? "warn" : "good"}`],
      ["Conciliação", order.reconciliation_status === "RECONCILED" ? "SKU conciliado" : "Sync pendente", `pill ${order.reconciliation_status === "RECONCILED" ? "good" : "warn"}`],
      ["Valor", money(order.total_amount), ""],
      ["Margem", order.margin_percent === null ? "Custo M9 pendente" : `${percent(order.margin_percent)} · ${money(order.margin_amount)}`, order.margin_percent === null ? "pill warn" : ""],
      ["Expedição", order.tracking_code || order.shipment_status || "Aguardando", order.tracking_code ? "mono" : ""],
      ["Atualização", dateTime(order.updated_at), ""],
    ];
    values.forEach(([label, value, className]) => {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      cell.append(textElement("span", className, value));
      row.append(cell);
    });
    return row;
  }));
}

function render(snapshot) {
  $("generated").textContent = `Atualizado em ${dateTime(snapshot.generated_at)}`;
  $("metric-orders").textContent = String(snapshot.orders.length);
  $("metric-reconciled").textContent = String(snapshot.reconciled_orders);
  $("metric-margin-gaps").textContent = String(snapshot.margin_pending_orders);
  renderChannels(snapshot.channels);
  renderOrders(snapshot.orders);
}

async function load({ announce = false } = {}) {
  const companyId = $("company").value;
  if (!companyId) return;
  $("refresh").disabled = true;
  try {
    render(await api(`sales/cockpit?company_id=${encodeURIComponent(companyId)}`));
    if (announce) notify("Canais atualizados com a posição mais recente.");
  } catch (error) {
    if (error.status === 401 || error.status === 403) showDenied();
    else notify(error.message);
  } finally {
    $("refresh").disabled = false;
  }
}

function showDenied() {
  $("access").hidden = true;
  $("cockpit").hidden = true;
  $("denied").hidden = false;
}

$("access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = $("access-token").value.trim();
  $("access-error").textContent = "";
  if (!token) return;
  try {
    const context = await api("admin/session-context");
    if (!context.permissions.includes("sales.orders.read")) {
      showDenied();
      return;
    }
    const companies = (await api("admin/companies?status=ACTIVE")).items;
    $("company").replaceChildren(...companies.map((company) => {
      const option = document.createElement("option");
      option.value = company.id;
      option.textContent = company.trade_name || company.legal_name;
      return option;
    }));
    $("access-token").value = "";
    $("access").hidden = true;
    $("cockpit").hidden = false;
    await load();
  } catch (error) {
    $("access-error").textContent = error.message;
  }
});
$("company").addEventListener("change", () => load({ announce: true }));
$("refresh").addEventListener("click", () => load({ announce: true }));
$("denied-back").addEventListener("click", () => {
  token = "";
  $("denied").hidden = true;
  $("access").hidden = false;
  $("access-token").focus();
});
$("access-token").focus();
