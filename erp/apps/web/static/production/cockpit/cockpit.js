const $ = (id) => document.getElementById(id);
let token = "";
let permissions = new Set();
let companies = [];
let noticeTimer = 0;

const statusLabel = {
  DRAFT: "Rascunho",
  RELEASED: "Liberada",
  IN_PROGRESS: "Em execução",
};
const centerState = { NORMAL: "Equilibrado", ATTENTION: "Atenção", BOTTLENECK: "Gargalo" };

async function api(path) {
  const response = await fetch(`/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  let body = null;
  try { body = await response.json(); } catch { /* resposta vazia */ }
  if (!response.ok) {
    const message = body?.error?.message || "Não foi possível carregar o cockpit.";
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}

function notify(message) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").classList.add("visible");
  noticeTimer = window.setTimeout(() => $("notice").classList.remove("visible"), 3000);
}

function number(value, digits = 1) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits }).format(Number(value));
}
function shortDate(value) {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" }).format(
    new Date(`${value}T12:00:00`),
  );
}
function dateTime(value) {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(value),
  );
}

function renderCenters(snapshot) {
  $("shift-basis").textContent = `Turno padrão · ${snapshot.standard_shift_minutes} min`;
  $("center-empty").hidden = snapshot.work_centers.length > 0;
  $("center-loads").replaceChildren(
    ...snapshot.work_centers.map((center) => {
      const article = document.createElement("article");
      article.className = `center-card ${center.state}`;
      article.innerHTML = `
        <header><span class="center-code"></span><span class="center-state"></span></header>
        <div class="center-number"><strong></strong><span></span></div>
        <div class="load-track" aria-label="Ocupação do centro"><i></i></div>
        <p class="capabilities"></p>`;
      article.querySelector(".center-code").textContent = center.code;
      article.querySelector(".center-state").textContent = centerState[center.state] || center.state;
      article.querySelector("strong").textContent = `${number(center.load_percent)}%`;
      article.querySelector(".center-number span").textContent =
        `${number(center.planned_minutes)} min · ${center.active_operations} operação(ões)`;
      article.querySelector(".load-track i").style.width = `${Math.min(Number(center.load_percent), 100)}%`;
      article.querySelector(".capabilities").textContent =
        center.capabilities.length ? center.capabilities.join(" · ") : "Sem capacidade classificada";
      return article;
    }),
  );
}

function renderAlerts(snapshot) {
  $("alert-count").textContent = String(snapshot.alerts.length);
  $("alert-empty").hidden = snapshot.alerts.length > 0;
  $("alerts").replaceChildren(
    ...snapshot.alerts.map((alert) => {
      const article = document.createElement("article");
      article.className = `alert ${alert.severity}`;
      const content = document.createElement("div");
      const title = document.createElement("strong");
      const message = document.createElement("p");
      title.textContent = alert.title;
      message.textContent = alert.message;
      content.append(title, message);
      article.append(content);
      return article;
    }),
  );
}

function renderOrders(snapshot) {
  $("orders-empty").hidden = snapshot.orders.length > 0;
  $("orders").replaceChildren(
    ...snapshot.orders.map((order) => {
      const row = document.createElement("tr");
      const late = new Date(`${order.due_on}T23:59:59`) < new Date() && order.status !== "COMPLETED";
      const cells = [
        ["Ordem", `<span class="order-number"></span>`],
        ["Estado", `<span class="status-pill ${order.status}"></span>`],
        ["Roteiro", `<span class="route"></span>`],
        ["Centro atual", `<span class="center"></span>`],
        ["Produzido", `<span class="produced"></span>`],
        ["Progresso", `<div class="progress-cell"><strong></strong><div><i></i></div></div>`],
        ["Prazo", `<span class="due${late ? " due-late" : ""}"></span>`],
        ["Sincronização", `<span class="sync-pill${order.synchronization_pending ? " pending" : ""}"></span>`],
      ];
      cells.forEach(([label, html]) => {
        const cell = document.createElement("td");
        cell.dataset.label = label;
        cell.innerHTML = html;
        row.append(cell);
      });
      row.querySelector(".order-number").textContent = order.order_number;
      row.querySelector(".status-pill").textContent = statusLabel[order.status] || order.status;
      row.querySelector(".route").textContent =
        `${order.completed_operations}/${order.total_operations} · ${order.current_operation || "Aguardando liberação"}`;
      row.querySelector(".center").textContent = order.current_work_center || "—";
      row.querySelector(".produced").textContent =
        `${number(order.good_quantity)} / ${number(order.planned_quantity)} ${order.planned_uom}`;
      row.querySelector(".progress-cell strong").textContent = `${number(order.progress_percent)}%`;
      row.querySelector(".progress-cell i").style.width = `${Math.min(Number(order.progress_percent), 100)}%`;
      row.querySelector(".due").textContent = shortDate(order.due_on);
      row.querySelector(".sync-pill").textContent = order.synchronization_pending
        ? "Na fila"
        : order.last_synchronization_at
          ? `Atualizada ${dateTime(order.last_synchronization_at)}`
          : "Estável";
      return row;
    }),
  );
}

function render(snapshot) {
  $("generated").textContent = `Atualizado em ${dateTime(snapshot.generated_at)}`;
  $("metric-active").textContent = String(snapshot.orders.length);
  $("metric-running").textContent = String(
    snapshot.orders.filter((value) => value.status === "IN_PROGRESS").length,
  );
  $("metric-risk").textContent = String(
    snapshot.alerts.filter((value) => value.severity === "CRITICAL").length,
  );
  const average = snapshot.work_centers.length
    ? snapshot.work_centers.reduce((sum, value) => sum + Number(value.load_percent), 0) /
      snapshot.work_centers.length
    : 0;
  $("metric-load").textContent = `${number(average)}%`;
  renderCenters(snapshot);
  renderAlerts(snapshot);
  renderOrders(snapshot);
}

async function load({ announce = false } = {}) {
  const companyId = $("company").value;
  if (!companyId) return;
  $("refresh").disabled = true;
  $("refresh").textContent = "Atualizando…";
  try {
    render(await api(`production/cockpit?company_id=${encodeURIComponent(companyId)}`));
    if (announce) notify("Cockpit atualizado com a posição mais recente.");
  } catch (error) {
    if (error.status === 401 || error.status === 403) showDenied();
    else notify(error.message);
  } finally {
    $("refresh").disabled = false;
    $("refresh").textContent = "Atualizar agora";
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
    permissions = new Set(context.permissions);
    if (!permissions.has("production.shop_floor.read")) {
      showDenied();
      return;
    }
    const result = await api("admin/companies?status=ACTIVE");
    companies = result.items;
    $("company").replaceChildren(
      ...companies.map((company) => {
        const option = document.createElement("option");
        option.value = company.id;
        option.textContent = company.trade_name || company.legal_name;
        return option;
      }),
    );
    $("access-token").value = "";
    $("access").hidden = true;
    $("denied").hidden = true;
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
  permissions = new Set();
  companies = [];
  $("denied").hidden = true;
  $("access").hidden = false;
  $("access-token").focus();
});
$("access-token").focus();
