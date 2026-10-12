const $ = (id) => document.getElementById(id);

const statusLabels = {
  DRAFT: "Rascunho",
  PENDING_APPROVAL: "Pendente de aprovação",
  APPROVED: "Aprovado",
  REJECTED: "Rejeitado",
  SCHEDULED: "Agendado",
  PAID: "Pago",
  OPEN: "Em aberto",
};

const approvalLabels = {
  NOT_REQUESTED: "Não solicitada",
  PENDING: "Pendente M22",
  APPROVED: "Aprovada",
  REJECTED: "Rejeitada",
};

const originLabels = {
  FISCAL_DOCUMENT: "Documento fiscal M11",
  PURCHASE_ORDER: "Pedido de compra M6",
};

function money(value, currency = "BRL") {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency,
  }).format(Number(value || 0));
}

function shortDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(
    new Date(`${value}T12:00:00Z`),
  );
}

function dateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function cell(value, className = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function badge(status) {
  const element = document.createElement("span");
  element.className = `status ${status}`;
  element.textContent = statusLabels[status] || status;
  return element;
}

function setGate(id, state, title, description) {
  const gate = $(id);
  gate.className = state;
  gate.querySelector("strong").textContent = title;
  gate.querySelector("span").textContent = description;
}

async function busy(button, action) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    return await action();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

export function mountFinance({ api, context, notice, enter }) {
  let payables = [];
  let selected = null;
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("finance").hidden = true;
    $("finance-nav").removeAttribute("aria-current");
  }

  function reset() {
    hide();
    payables = [];
    selected = null;
    $("finance-payable-rows").replaceChildren();
    $("finance-installment-rows").replaceChildren();
    $("finance-audit").replaceChildren();
    $("finance-detail").hidden = true;
  }

  function renderMetrics() {
    const now = new Date();
    const horizon = new Date(now);
    horizon.setDate(horizon.getDate() + 30);
    const installments = payables.flatMap((item) => item.installments || []);
    const dueSoon = installments.filter((item) => {
      const due = new Date(`${item.due_date}T23:59:59`);
      return item.status !== "PAID" && due >= now && due <= horizon;
    }).length;
    const outstanding = payables.reduce(
      (total, item) => total + Number(item.outstanding_amount || 0),
      0,
    );
    $("finance-count").textContent = String(payables.length);
    $("finance-outstanding").textContent = money(outstanding);
    $("finance-pending").textContent = String(
      payables.filter((item) => item.status === "PENDING_APPROVAL").length,
    );
    $("finance-due").textContent = String(dueSoon);
  }

  function renderList() {
    const rows = $("finance-payable-rows");
    rows.replaceChildren();
    for (const item of payables) {
      const row = document.createElement("tr");
      const number = cell("");
      const strong = document.createElement("strong");
      const small = document.createElement("small");
      strong.textContent = item.number;
      small.textContent = item.supplier_tax_id;
      number.append(strong, small);
      row.append(number);
      const openInstallments = (item.installments || [])
        .filter((installment) => installment.status !== "PAID")
        .sort((left, right) => left.due_date.localeCompare(right.due_date));
      const due = cell("", "finance-row-due");
      const dueDate = document.createElement("strong");
      const balance = document.createElement("small");
      dueDate.textContent = shortDate(openInstallments[0]?.due_date);
      balance.textContent = money(item.outstanding_amount, item.currency);
      due.append(dueDate, balance);
      row.append(due);
      const state = cell("", "finance-row-action");
      state.append(badge(item.status));
      const button = document.createElement("button");
      button.className = "quiet";
      button.textContent = "Analisar →";
      button.setAttribute("aria-label", `Analisar título ${item.number}`);
      button.addEventListener("click", () =>
        loadDetail(item.id).catch((error) => notice(error.message)),
      );
      state.append(button);
      row.append(state);
      rows.append(row);
    }
    $("finance-empty").hidden = payables.length > 0;
    renderMetrics();
  }

  async function loadList() {
    const refresh = $("finance-refresh");
    const status = $("finance-status-filter").value;
    refresh.disabled = true;
    refresh.setAttribute("aria-busy", "true");
    try {
      const result = await api(
        `finance/payables?company_id=${context().company}&page=1&page_size=100${
          status ? `&status=${encodeURIComponent(status)}` : ""
        }`,
      );
      payables = result.data;
      renderList();
      if (selected) {
        const stillVisible = payables.some((item) => item.id === selected.id);
        if (stillVisible) await loadDetail(selected.id);
        else clearDetail();
      }
    } finally {
      refresh.disabled = false;
      refresh.removeAttribute("aria-busy");
    }
  }

  function clearDetail() {
    selected = null;
    $("finance-detail").hidden = true;
    $("finance-selected-title").textContent = "Selecione um título";
    $("finance-selected-meta").textContent =
      "A trilha financeira e a governança aparecerão aqui.";
    $("finance-selected-version").textContent = "—";
  }

  function renderGovernance(item) {
    const governance = item.governance;
    const alert = $("finance-governance-alert");
    alert.hidden = true;
    alert.className = "finance-alert";
    if (!governance) {
      setGate("finance-gate-fiscal", "neutral", "Sem fatos", "aguardando avaliação");
      setGate("finance-gate-purchasing", "neutral", "Sem fatos", "aguardando avaliação");
      setGate("finance-gate-approval", "neutral", "Não solicitada", "governança ainda não aberta");
      $("finance-authority").textContent = "Não configurada";
      $("finance-sod-rule").textContent = "A regra SoD será aplicada na submissão";
      return;
    }
    setGate(
      "finance-gate-fiscal",
      governance.fiscal_blocked ? "blocked" : "clear",
      governance.fiscal_blocked ? "Bloqueado" : "Conforme",
      governance.fiscal_blocked ? "divergência fiscal aberta" : "sem divergência fiscal",
    );
    setGate(
      "finance-gate-purchasing",
      governance.purchasing_blocked ? "blocked" : "clear",
      governance.purchasing_blocked ? "Bloqueado" : "Conforme",
      governance.purchasing_blocked ? "divergência físico-compras" : "sem divergência de compras",
    );
    const approvalState = {
      PENDING: "pending",
      APPROVED: "clear",
      REJECTED: "blocked",
      NOT_REQUESTED: "neutral",
    }[governance.approval_status];
    setGate(
      "finance-gate-approval",
      approvalState,
      approvalLabels[governance.approval_status] || governance.approval_status,
      governance.workflow_instance_id
        ? `workflow ${governance.workflow_instance_id.slice(0, 8)}`
        : "sem instância M22",
    );
    $("finance-authority").textContent = governance.authority_limit
      ? money(governance.authority_limit, item.currency)
      : "Aprovação formal";
    $("finance-sod-rule").textContent = `Autoaprovação bloqueada acima de ${money(
      governance.sod_threshold,
      item.currency,
    )}`;
    if (governance.blocked) {
      alert.textContent =
        "Liberação suspensa: resolva as divergências destacadas antes de aprovar ou agendar este título.";
      alert.classList.add("blocked");
      alert.hidden = false;
    } else if (governance.approval_status === "PENDING") {
      alert.textContent =
        "Decisão pendente no M22. A segregação de funções impede a autoaprovação quando aplicável.";
      alert.classList.add("pending");
      alert.hidden = false;
    }
  }

  function renderDetail(item) {
    selected = item;
    $("finance-detail").hidden = false;
    $("finance-selected-title").textContent = item.number;
    $("finance-selected-meta").textContent = `${item.supplier_tax_id} · ${statusLabels[item.status] || item.status}`;
    $("finance-selected-version").textContent = `ETag · v${item.version}`;
    $("finance-total").textContent = money(item.total_amount, item.currency);
    $("finance-adjustment-summary").textContent = `Desconto ${money(
      item.discount_amount,
      item.currency,
    )} · Acréscimo ${money(item.surcharge_amount, item.currency)}`;
    $("finance-origin").textContent = item.provisional_entry
      ? originLabels[item.provisional_entry.origin] || item.provisional_entry.origin
      : "Lançamento manual";
    $("finance-origin-meta").textContent = item.provisional_entry
      ? `${item.provisional_entry.status} · fonte ${item.provisional_entry.source_id.slice(0, 8)}`
      : "Sem provisão vinculada";
    setGate(
      "finance-gate-payment",
      item.status === "REJECTED" ? "blocked" : item.status === "SCHEDULED" || item.status === "PAID" ? "clear" : "pending",
      statusLabels[item.status] || item.status,
      item.status === "PAID" ? "obrigação liquidada" : "estado do título",
    );
    renderGovernance(item);

    $("finance-installment-rows").replaceChildren(
      ...item.installments.map((installment) => {
        const row = document.createElement("tr");
        row.append(cell(String(installment.number)));
        row.append(cell(shortDate(installment.due_date)));
        row.append(cell(money(installment.amount, item.currency), "numeric"));
        const state = cell("");
        state.append(badge(installment.status));
        row.append(state);
        return row;
      }),
    );
    $("finance-audit").replaceChildren(
      ...item.audit_history.map((entry) => {
        const line = document.createElement("li");
        const strong = document.createElement("strong");
        const small = document.createElement("small");
        strong.textContent = entry.operation.replaceAll("_", " ");
        small.textContent = `${dateTime(entry.occurred_at)} · ator ${
          entry.actor_user_id?.slice(0, 8) || "sistema"
        }`;
        line.append(strong, small);
        return line;
      }),
    );
    $("finance-discount").value = item.discount_amount;
    $("finance-surcharge").value = item.surcharge_amount;
    const blocked = Boolean(item.governance?.blocked);
    $("finance-submit").hidden =
      !can("finance.payable.create") || item.status !== "DRAFT" || blocked;
    $("finance-adjustment-form").hidden =
      !can("finance.payable.adjust") || item.status !== "DRAFT";
    $("finance-schedule").hidden =
      !can("finance.payable.adjust") || item.status !== "APPROVED" || blocked;
  }

  async function loadDetail(id) {
    const item = await api(`finance/payables/${id}?company_id=${context().company}`);
    renderDetail(item);
  }

  async function show() {
    if (!can("finance.payable.read")) return;
    enter();
    $("finance").hidden = false;
    clearDetail();
    await loadList();
  }

  $("finance-refresh").addEventListener("click", () =>
    loadList().catch((error) => notice(error.message)),
  );
  $("finance-status-filter").addEventListener("change", () =>
    loadList().catch((error) => notice(error.message)),
  );
  $("finance-submit").addEventListener("click", async (event) => {
    if (!selected) return;
    const button = event.currentTarget;
    try {
      await busy(button, async () => {
        await api(
          `finance/payables/${selected.id}/submit-for-approval?company_id=${context().company}`,
          { method: "POST", version: selected.version },
        );
        await loadList();
        notice("Título submetido à governança de alçada.");
      });
    } catch (error) {
      if (error.code === "SOD_VIOLATION") {
        const alert = $("finance-governance-alert");
        alert.textContent =
          "SOD_VIOLATION · O criador não pode aprovar a própria obrigação acima da alçada.";
        alert.className = "finance-alert blocked";
        alert.hidden = false;
      }
      notice(error.message);
    }
  });
  $("finance-adjustment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selected) return;
    const button = event.submitter;
    await busy(button, async () => {
      await api(
        `finance/payables/${selected.id}/adjustments?company_id=${context().company}`,
        {
          method: "PATCH",
          version: selected.version,
          body: {
            discount_amount: $("finance-discount").value,
            surcharge_amount: $("finance-surcharge").value,
          },
        },
      );
      await loadList();
      notice("Ajustes financeiros aplicados com controle de versão.");
    });
  });
  $("finance-schedule").addEventListener("click", async (event) => {
    if (!selected) return;
    if (!confirm("Agendar todas as parcelas abertas deste título?")) return;
    const button = event.currentTarget;
    await busy(button, async () => {
      await api(
        `finance/payables/${selected.id}/schedule?company_id=${context().company}`,
        {
          method: "POST",
          version: selected.version,
          key: crypto.randomUUID(),
          body: { schedule_ids: selected.installments.map(() => crypto.randomUUID()) },
        },
      );
      await loadList();
      notice("Parcelas agendadas com idempotência e versão confirmadas.");
    });
  });

  return { hide, reset, show };
}
