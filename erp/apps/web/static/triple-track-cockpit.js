const $ = (id) => document.getElementById(id);
let accessToken = "";
let permissions = new Set();
let noticeTimer = 0;

const tracks = {
  fiscal: {
    permission: "fiscal.tax_rule.read",
    endpoint: "fiscal/cockpit",
    itemKey: "rules",
    title: "Governança fiscal",
    subtitle: "Versões tributárias e vigências",
    metrics: [
      ["Regras visíveis", "total_rules"],
      ["Em elaboração", "draft_rules"],
      ["Ativas", "active_rules"],
      ["Encerradas", "retired_rules"],
    ],
    columns: [
      ["Regra", (item) => `${item.code} · ${item.version_code}`],
      ["Estado", (item) => status(item.status), "status"],
      ["Fluxo", (item) => item.flow === "INBOUND" ? "Entrada" : "Saída"],
      ["NCM / CFOP", (item) => `${item.ncm} / ${item.cfop}`],
      ["Vigência", (item) => `${shortDate(item.effective_from)} → ${item.effective_until ? shortDate(item.effective_until) : "aberta"}`],
      ["ICMS", (item) => percent(item.icms_rate)],
      ["PIS / COFINS", (item) => `${percent(item.pis_rate)} / ${percent(item.cofins_rate)}`],
      ["Versão", (item) => `v${item.version}`],
    ],
    empty: "Nenhuma regra fiscal foi encontrada para esta empresa.",
  },
  procurement: {
    permission: "procurement.rfq.read",
    endpoint: "procurement/cockpit",
    itemKey: "rfqs",
    title: "Mesa de cotações",
    subtitle: "Concorrências, propostas e adjudicações",
    metrics: [
      ["RFQs visíveis", "total_rfqs"],
      ["Abertas", "open_rfqs"],
      ["Em decisão", "closed_rfqs"],
      ["Adjudicadas", "awarded_rfqs"],
    ],
    columns: [
      ["Cotação", (item) => item.code],
      ["Estado", (item) => status(item.status), "status"],
      ["Prazo", (item) => shortDate(item.response_deadline)],
      ["Itens", (item) => number(item.item_count, 0)],
      ["Fornecedores", (item) => number(item.invited_supplier_count, 0)],
      ["Propostas", (item) => number(item.quote_count, 0)],
      ["Menor comparável", (item) => item.lowest_quote_amount === null ? "—" : money(item.lowest_quote_amount, item.comparable_quote_currency)],
      ["Versão", (item) => `v${item.version}`],
    ],
    empty: "Nenhuma concorrência foi encontrada para esta empresa.",
  },
  finance: {
    permission: "finance.treasury.read",
    endpoint: "finance/cockpit",
    itemKey: "payments",
    title: "Alçadas de pagamento",
    subtitle: "Solicitações, aprovações e envio à tesouraria",
    metrics: [
      ["Solicitações", "total_requests"],
      ["Em aprovação", "pending_requests"],
      ["Valor pendente", "pending_amount", "money"],
      ["Valor aprovado", "approved_amount", "money"],
    ],
    columns: [
      ["Solicitação", (item) => item.code],
      ["Estado", (item) => status(item.status), "status"],
      ["Agendamento", (item) => shortDate(item.scheduled_on)],
      ["Finalidade", (item) => item.purpose],
      ["Parcelas", (item) => number(item.item_count, 0)],
      ["Valor", (item) => money(item.total_amount, item.currency)],
      ["Aprovador", (item) => item.approved_by ? compactId(item.approved_by) : "Aguardando"],
      ["Versão", (item) => `v${item.version}`],
    ],
    empty: "Nenhuma solicitação de pagamento foi encontrada para esta empresa.",
  },
};

const track = tracks[document.body.dataset.track];

async function api(path) {
  const response = await fetch(`/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  let body = null;
  try { body = await response.json(); } catch { /* contrato sem corpo */ }
  if (!response.ok) {
    const error = new Error(body?.error?.message || "Não foi possível carregar o painel.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function number(value, digits = 2) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits }).format(Number(value));
}
function money(value, currency = "BRL") {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: currency || "BRL" }).format(Number(value));
}
function percent(value) { return `${number(Number(value) * 100, 2)}%`; }
function shortDate(value) {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}
function dateTime(value) {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" })
    .format(new Date(value));
}
function compactId(value) { return `${value.slice(0, 8)}…${value.slice(-4)}`; }
function status(value) {
  return ({
    DRAFT: "Rascunho", ACTIVE: "Ativa", RETIRED: "Encerrada", OPEN: "Aberta",
    CLOSED: "Em decisão", AWARDED: "Adjudicada", CANCELLED: "Cancelada",
    PENDING_APPROVAL: "Em aprovação", APPROVED: "Aprovada", REJECTED: "Rejeitada",
    BATCHED: "Em lote",
  })[value] || value;
}

function notify(message) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").classList.add("visible");
  noticeTimer = window.setTimeout(() => $("notice").classList.remove("visible"), 3200);
}

function renderMetrics(snapshot) {
  $("metrics").replaceChildren(...track.metrics.map(([label, key, format]) => {
    const card = document.createElement("article");
    const caption = document.createElement("span");
    const value = document.createElement("strong");
    caption.textContent = label;
    const raw = snapshot[key];
    value.textContent = format === "money" ? money(raw) : number(raw, 0);
    card.append(caption, value);
    return card;
  }));
}

function renderTable(snapshot) {
  const items = snapshot[track.itemKey];
  $("queue-title").textContent = track.title;
  $("queue-subtitle").textContent = track.subtitle;
  $("queue-empty").textContent = track.empty;
  $("queue-empty").hidden = items.length > 0;
  const header = document.createElement("tr");
  track.columns.forEach(([label]) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    header.append(cell);
  });
  $("queue-head").replaceChildren(header);
  $("queue-body").replaceChildren(...items.map((item) => {
    const row = document.createElement("tr");
    track.columns.forEach(([label, formatter, kind]) => {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      if (kind === "status") {
        const pill = document.createElement("span");
        pill.className = `status status-${item.status.toLowerCase()}`;
        pill.textContent = formatter(item);
        cell.append(pill);
      } else {
        cell.textContent = formatter(item);
      }
      row.append(cell);
    });
    return row;
  }));
}

function render(snapshot) {
  $("generated").textContent = `Posição gerada em ${dateTime(snapshot.generated_at)}`;
  renderMetrics(snapshot);
  renderTable(snapshot);
}

async function load({ announce = false } = {}) {
  const companyId = $("company").value;
  if (!companyId) return;
  $("refresh").disabled = true;
  $("refresh").textContent = "Atualizando…";
  try {
    render(await api(`${track.endpoint}?company_id=${encodeURIComponent(companyId)}`));
    if (announce) notify("Posição atualizada com sucesso.");
  } catch (error) {
    if (error.status === 401 || error.status === 403) showDenied();
    else notify(error.message);
  } finally {
    $("refresh").disabled = false;
    $("refresh").textContent = "Atualizar posição";
  }
}

function showDenied() {
  $("access").hidden = true;
  $("cockpit").hidden = true;
  $("denied").hidden = false;
}

$("access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  accessToken = $("access-token").value.trim();
  $("access-error").textContent = "";
  if (!accessToken) return;
  try {
    const context = await api("admin/session-context");
    permissions = new Set(context.permissions);
    if (!permissions.has(track.permission)) {
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
  accessToken = "";
  permissions = new Set();
  $("denied").hidden = true;
  $("access").hidden = false;
  $("access-token").focus();
});
$("permission-code").textContent = track.permission;
$("access-token").focus();
