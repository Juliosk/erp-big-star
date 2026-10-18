const $ = (id) => document.getElementById(id);

const statusLabels = {
  DRAFT: "Rascunho",
  PENDING_APPROVAL: "Em alçada M22",
  APPROVED: "Aprovado",
  RELEASED: "Remessa liberada",
  SUBMITTED: "Enviado ao banco",
  CONFIRMED: "Confirmado",
  FAILED: "Falha bancária",
};

const reviewLabels = {
  BLOCKED: "Bloqueado",
  REVIEW_REQUIRED: "Revisão necessária",
  CLEARED: "Elegível",
};

const reviewReasonLabels = {
  MatchingDiscrepancyDetected: "Divergência do Three-Way Match ainda não resolvida.",
  MatchingOverrideRejected: "O override da divergência foi rejeitado pela alçada.",
  PayableAdjusted: "O valor do título mudou depois da composição do lote.",
  PayableCancelled: "Um título vinculado ao lote foi cancelado.",
  PayableRejected: "Um título vinculado perdeu a elegibilidade de pagamento.",
  FiscalReceivingReconciled: "A conciliação físico-fiscal exige nova avaliação.",
  ApprovalDecisionMade: "A decisão M22 alterou a elegibilidade do lote.",
};

const money = (value, currency = "BRL") =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(
    Number(value || 0),
  );

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

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

function badge(status, prefix = "") {
  return node(
    "span",
    `status ${prefix}${status || "DRAFT"}`,
    reviewLabels[status] || statusLabels[status] || status || "Rascunho",
  );
}

function shortId(value) {
  return String(value || "—").slice(0, 8);
}

async function busy(button, callback) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    return await callback();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

export function mountTreasury({ api, context, notice, enter, openWorkflow }) {
  let batches = [];
  let selected = null;
  let page = 1;
  let hasMore = false;
  let artifact = null;
  const workflowIds = new Map();
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("treasury").hidden = true;
    $("treasury-nav").removeAttribute("aria-current");
    if (window.location.pathname.replace(/\/$/, "").endsWith("/treasury")) {
      history.replaceState({}, "", "/ui/");
    }
  }

  function reset() {
    hide();
    batches = [];
    selected = null;
    page = 1;
    hasMore = false;
    artifact = null;
    workflowIds.clear();
    $("treasury-batch-list").replaceChildren();
    clearDetail();
  }

  function visibleBatches() {
    const filter = $("treasury-review-filter").value;
    if (!filter) return batches;
    return batches.filter((batch) => {
      if (filter === "CLEAR") return !batch.review?.blocked;
      if (filter === "BANK_FAILURE") return batch.status === "FAILED";
      return batch.review?.status === filter;
    });
  }

  function renderMetrics() {
    const visible = visibleBatches();
    const blocked = visible.filter(
      (batch) => batch.review?.blocked || batch.status === "FAILED",
    );
    const releasable = visible.filter(
      (batch) =>
        !batch.review?.blocked &&
        ["DRAFT", "PENDING_APPROVAL", "APPROVED", "RELEASED"].includes(
          batch.status,
        ),
    );
    $("treasury-count").textContent = String(visible.length);
    $("treasury-total").textContent = money(
      visible.reduce((sum, batch) => sum + Number(batch.total_amount), 0),
    );
    $("treasury-blocked").textContent = String(blocked.length);
    $("treasury-ready").textContent = money(
      releasable.reduce((sum, batch) => sum + Number(batch.total_amount), 0),
    );
  }

  function renderQueue() {
    const values = visibleBatches();
    $("treasury-batch-list").replaceChildren(
      ...values.map((batch) => {
        const button = node("button", "treasury-batch-card");
        button.type = "button";
        button.dataset.batchId = batch.id;
        button.setAttribute("aria-current", selected?.batch.id === batch.id);
        if (batch.review?.blocked || batch.status === "FAILED") {
          button.classList.add("blocked");
        }
        const heading = node("span", "treasury-batch-card-head");
        heading.append(node("strong", "mono", batch.code), badge(batch.status));
        const value = node("span", "treasury-batch-card-value");
        value.append(
          node("strong", "", money(batch.total_amount, batch.currency)),
          node("small", "", `${batch.items.length} pagamento(s)`),
        );
        const footer = node("span", "treasury-batch-card-foot");
        footer.append(
          node("span", "", `Agenda ${shortDate(batch.scheduled_date)}`),
          batch.review
            ? badge(batch.review.status, "review-")
            : node("span", "treasury-clear-label", "Sem bloqueios"),
        );
        button.append(heading, value, footer);
        button.addEventListener("click", () =>
          openBatch(batch.id).catch((error) => notice(error.message)),
        );
        return button;
      }),
    );
    $("treasury-empty").hidden = values.length > 0;
    $("treasury-page").textContent = `Página ${page}`;
    $("treasury-previous").disabled = page === 1;
    $("treasury-next").disabled = !hasMore;
    renderMetrics();
  }

  async function loadList({ keepSelection = true } = {}) {
    const status = $("treasury-status-filter").value;
    const result = await api(
      `finance/treasury/batches?company_id=${context().company}&page=${page}&page_size=50${
        status ? `&status=${encodeURIComponent(status)}` : ""
      }`,
    );
    batches = result.data;
    hasMore = result.meta.has_more;
    renderQueue();
    if (keepSelection && selected) {
      if (batches.some((batch) => batch.id === selected.batch.id)) {
        await openBatch(selected.batch.id);
      } else {
        clearDetail();
      }
    }
  }

  function clearDetail() {
    selected = null;
    artifact = null;
    $("treasury-dossier-empty").hidden = false;
    $("treasury-dossier-content").hidden = true;
    $("treasury-artifact").hidden = true;
    $("treasury-item-rows").replaceChildren();
    $("treasury-audit").replaceChildren();
    $("treasury-review-reasons").replaceChildren();
  }

  function setStage(id, state, title, description) {
    const stage = $(id);
    stage.className = state;
    stage.querySelector("strong").textContent = title;
    stage.querySelector("small").textContent = description;
  }

  function renderReleaseRail(batch) {
    const review = batch.review;
    setStage(
      "treasury-stage-eligibility",
      review?.blocked ? "blocked" : "clear",
      review?.blocked ? reviewLabels[review.status] : "Elegível",
      review?.blocked ? "há fatos externos pendentes" : "títulos e matching conformes",
    );
    setStage(
      "treasury-stage-approval",
      batch.status === "DRAFT"
        ? "waiting"
        : batch.status === "PENDING_APPROVAL"
          ? "active"
          : "clear",
      batch.status === "DRAFT"
        ? "Não solicitada"
        : batch.status === "PENDING_APPROVAL"
          ? "Em análise"
          : "Concluída",
      "segregação de funções M22",
    );
    setStage(
      "treasury-stage-remittance",
      batch.status === "FAILED"
        ? "blocked"
        : ["RELEASED", "SUBMITTED", "CONFIRMED"].includes(batch.status)
          ? "clear"
          : "waiting",
      batch.status === "FAILED"
        ? "Rejeitada"
        : ["RELEASED", "SUBMITTED", "CONFIRMED"].includes(batch.status)
          ? "Transmitida"
          : "Aguardando",
      batch.submission_protocol || batch.remittance_format.replace("_", " "),
    );
    setStage(
      "treasury-stage-bank",
      batch.status === "CONFIRMED"
        ? "clear"
        : batch.status === "FAILED"
          ? "blocked"
          : "waiting",
      batch.status === "CONFIRMED"
        ? "Liquidado"
        : batch.status === "FAILED"
          ? "Falha bancária"
          : "Sem confirmação",
      batch.bank_confirmation_protocol ||
        batch.bank_failure_protocol ||
        "retorno ainda não recebido",
    );
  }

  function renderReview(review) {
    const panel = $("treasury-review-panel");
    panel.className = `treasury-review-panel ${review?.blocked ? "blocked" : "clear"}`;
    $("treasury-review-title").textContent = review?.blocked
      ? reviewLabels[review.status] || review.status
      : "Lote liberado para seguir";
    $("treasury-review-meta").textContent = review
      ? `Revisão ${review.revision} · último fato ${dateTime(review.last_event_at)}`
      : "Nenhuma divergência assíncrona registrada.";
    const reasons = review?.reasons || [];
    $("treasury-review-reasons").replaceChildren(
      ...reasons.slice(-5).reverse().map((reason) => {
        const item = node("li", "");
        const eventType = String(reason.event_type || "evento");
        item.append(
          node(
            "strong",
            "",
            reviewReasonLabels[eventType] ||
              String(reason.reason || "Reavaliação de elegibilidade"),
          ),
          node(
            "small",
            "mono",
            `${eventType} · v${String(
              reason.aggregate_version || "—",
            )}`,
          ),
        );
        return item;
      }),
    );
  }

  function renderArtifact(value) {
    artifact = value;
    const panel = $("treasury-artifact");
    panel.hidden = !value;
    if (!value) return;
    $("treasury-artifact-name").textContent = value.filename;
    $("treasury-artifact-meta").textContent = `${value.record_count} registro(s) · ${money(
      value.total_amount,
    )} · SHA-256 ${value.checksum_sha256.slice(0, 12)}…`;
    $("treasury-artifact-kind").textContent = value.dry_run
      ? "SIMULAÇÃO"
      : "REMESSA OFICIAL";
  }

  function renderDetail(detail) {
    selected = detail;
    const batch = detail.batch;
    $("treasury-dossier-empty").hidden = true;
    $("treasury-dossier-content").hidden = false;
    $("treasury-selected-code").textContent = batch.code;
    $("treasury-selected-meta").textContent = `${statusLabels[batch.status] || batch.status} · agenda ${shortDate(batch.scheduled_date)}`;
    $("treasury-selected-version").textContent = `ETag · v${batch.version}`;
    $("treasury-selected-total").textContent = money(batch.total_amount, batch.currency);
    $("treasury-selected-account").textContent = shortId(batch.treasury_account_id);
    $("treasury-selected-format").textContent = `${batch.remittance_format.replace("_", " ")} · ${batch.execution_mode}`;
    renderReleaseRail(batch);
    renderReview(batch.review);

    $("treasury-item-rows").replaceChildren(
      ...batch.items.map((item) => {
        const row = document.createElement("tr");
        const beneficiary = node("td", "");
        beneficiary.append(
          node("strong", "", item.beneficiary_holder_name),
          node("small", "mono", `Fornecedor ${shortId(item.supplier_id)}`),
        );
        const bank = node("td", "");
        bank.append(
          node("strong", "mono", `${item.beneficiary_bank_code} · ${item.beneficiary_account_masked}`),
          node("small", "", `Vencimento ${shortDate(item.due_date)}`),
        );
        row.append(
          beneficiary,
          bank,
          node("td", "numeric", money(item.amount, item.currency)),
        );
        return row;
      }),
    );

    $("treasury-audit").replaceChildren(
      ...detail.audit_history.slice().reverse().map((entry) => {
        const item = node("li", "");
        item.append(
          node(
            "strong",
            "",
            `${entry.from_status ? `${statusLabels[entry.from_status] || entry.from_status} → ` : ""}${statusLabels[entry.to_status] || entry.to_status}`,
          ),
          node(
            "small",
            "",
            `${dateTime(entry.occurred_at)} · ator ${shortId(entry.actor_id)} · v${entry.aggregate_version}`,
          ),
        );
        return item;
      }),
    );

    const blocked = Boolean(batch.review?.blocked);
    $("treasury-dry-run").hidden = !can("finance.treasury_batch.create");
    $("treasury-remittance").hidden =
      !can("finance.treasury_batch.execute") ||
      blocked ||
      ["SUBMITTED", "CONFIRMED", "FAILED"].includes(batch.status);
    $("treasury-remittance").textContent =
      batch.status === "DRAFT"
        ? "Solicitar alçada M22"
        : batch.status === "PENDING_APPROVAL"
          ? "Validar aprovação e gerar remessa"
          : "Gerar e enviar remessa";
    $("treasury-workflow-field").hidden =
      batch.status !== "PENDING_APPROVAL" || blocked;
    $("treasury-open-workflow").hidden = batch.status !== "PENDING_APPROVAL";
    $("treasury-workflow-id").value = workflowIds.get(batch.id) || "";
    $("treasury-action-blocked").hidden = !blocked;
    renderArtifact(null);
  }

  async function openBatch(id) {
    const detail = await api(
      `finance/treasury/batches/${id}?company_id=${context().company}`,
    );
    renderDetail(detail);
    renderQueue();
  }

  async function show() {
    if (!can("finance.treasury.read")) return;
    enter();
    history.replaceState({}, "", "/ui/treasury");
    $("treasury").hidden = false;
    page = 1;
    clearDetail();
    await loadList({ keepSelection: false });
  }

  $("treasury-refresh").addEventListener("click", () =>
    loadList().catch((error) => notice(error.message)),
  );
  $("treasury-status-filter").addEventListener("change", () => {
    page = 1;
    loadList({ keepSelection: false }).catch((error) => notice(error.message));
  });
  $("treasury-review-filter").addEventListener("change", () => renderQueue());
  $("treasury-previous").addEventListener("click", () => {
    page -= 1;
    loadList({ keepSelection: false }).catch((error) => notice(error.message));
  });
  $("treasury-next").addEventListener("click", () => {
    page += 1;
    loadList({ keepSelection: false }).catch((error) => notice(error.message));
  });
  $("treasury-dry-run").addEventListener("click", async (event) => {
    if (!selected) return;
    const button = event.currentTarget;
    await busy(button, async () => {
      const result = await api(
        `finance/treasury/batches/${selected.batch.id}/dry-run?company_id=${context().company}`,
        {
          method: "POST",
          version: selected.batch.version,
          key: crypto.randomUUID(),
        },
      );
      renderArtifact(result.remittance);
      notice("Simulação bancária concluída sem efetivar a remessa.");
    });
  });
  $("treasury-remittance").addEventListener("click", async (event) => {
    if (!selected) return;
    const button = event.currentTarget;
    const batch = selected.batch;
    const workflowId = $("treasury-workflow-id").value.trim();
    if (batch.status === "PENDING_APPROVAL" && !workflowId) {
      notice("Informe a instância M22 aprovada antes de gerar a remessa.");
      return;
    }
    await busy(button, async () => {
      const result = await api(
        `finance/treasury/batches/${batch.id}/remittance?company_id=${context().company}`,
        {
          method: "POST",
          version: batch.version,
          key: crypto.randomUUID(),
          body: {
            workflow_instance_id: workflowId || null,
          },
        },
      );
      if (result.workflow_instance_id) {
        workflowIds.set(batch.id, result.workflow_instance_id);
      }
      await loadList({ keepSelection: false });
      await openBatch(batch.id);
      if (result.remittance) {
        renderArtifact(result.remittance);
        notice("Remessa gerada e submetida com rastreabilidade transacional.");
      } else {
        notice("Lote encaminhado para a alçada M22.");
      }
    });
  });
  $("treasury-open-workflow").addEventListener("click", () => openWorkflow());
  $("treasury-download").addEventListener("click", () => {
    if (!artifact) return;
    const bytes = Uint8Array.from(atob(artifact.content_base64), (char) =>
      char.charCodeAt(0),
    );
    const url = URL.createObjectURL(
      new Blob([bytes], { type: artifact.media_type || "application/octet-stream" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.filename;
    link.click();
    URL.revokeObjectURL(url);
  });

  return { hide, reset, show };
}
