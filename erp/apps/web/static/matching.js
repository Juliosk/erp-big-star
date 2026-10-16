const $ = (id) => document.getElementById(id);

const statusLabels = {
  PENDING: "Pendente",
  RUNNING: "Em execução",
  MATCHED: "Conciliado",
  DISCREPANCY_DETECTED: "Divergência detectada",
  OVERRIDDEN: "Override aprovado",
  REJECTED: "Rejeitado",
  PRICE_MISMATCH: "Preço divergente",
  QUANTITY_MISMATCH: "Quantidade divergente",
  TOLERANCE_EXCEEDED: "Tolerância excedida",
};

const reasonLabels = {
  UNIT_PRICE_TOLERANCE_EXCEEDED: "Preço unitário fora da tolerância",
  QUANTITY_TOLERANCE_EXCEEDED: "Quantidade fora da tolerância",
  ROUNDING_TOLERANCE_EXCEEDED: "Diferença de arredondamento excedida",
};

const money = (value, currency = "BRL") =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(Number(value));

const decimal = (value) =>
  new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 }).format(Number(value));

const shortId = (value) => String(value || "—").slice(0, 8);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusBadge(status) {
  return element("span", `status ${status || "PENDING"}`, statusLabels[status] || status || "Pendente");
}

export function mountMatching({ api, context, notice }) {
  let sessions = [];
  let selected = null;
  let workflow = null;
  let exceptionsOnly = false;

  const can = (permission) => context().permissions.has(permission);

  function reset() {
    sessions = [];
    selected = null;
    workflow = null;
    exceptionsOnly = false;
    $("matching-cockpit").hidden = true;
    $("matching-session-list").replaceChildren();
    $("matching-line-cards").replaceChildren();
    $("matching-audit-list").replaceChildren();
    $("matching-dossier-content").hidden = true;
    $("matching-dossier-empty").hidden = false;
  }

  function renderQueue() {
    $("matching-session-count").textContent = String(sessions.length);
    $("matching-session-empty").hidden = sessions.length > 0;
    $("matching-session-list").replaceChildren(
      ...sessions.map((session) => {
        const button = element("button", "matching-session-item");
        button.type = "button";
        button.dataset.sessionId = session.id;
        button.setAttribute("aria-current", selected?.session.id === session.id ? "true" : "false");
        const header = element("span", "matching-session-item-head");
        header.append(element("strong", "mono", `#${shortId(session.id)}`), statusBadge(session.status));
        const source = element(
          "span",
          "matching-session-source mono",
          `PO ${shortId(session.snapshot.purchase_order.id)} · v${session.version}`,
        );
        const result = element(
          "small",
          "matching-session-result",
          session.report_status ? statusLabels[session.report_status] || session.report_status : "Aguardando execução",
        );
        button.append(header, source, result);
        button.addEventListener("click", () => openSession(session.id).catch(showError));
        return button;
      }),
    );
  }

  function sourceCard(kind, label, reference, amount, currency) {
    const card = element("article", `matching-source-card ${kind}`);
    card.append(
      element("small", "matching-source-label", label),
      element("strong", "matching-source-amount", money(amount, currency)),
      element("span", "mono", `${shortId(reference.id)} · v${reference.version}`),
    );
    return card;
  }

  function renderLine(line) {
    const card = element("article", `matching-line-card ${line.result_status || "PENDING"}`);
    const heading = element("div", "matching-line-heading");
    heading.append(element("strong", "mono", line.match_key), statusBadge(line.result_status));
    const values = element("div", "matching-line-values");
    const purchase = element("div", "purchase");
    purchase.append(
      element("small", "", "Pedido"),
      element("strong", "", `${decimal(line.ordered_quantity)} × ${money(line.ordered_unit_price, line.currency)}`),
    );
    const received = element("div", "fiscal");
    received.append(
      element("small", "", "Recebido / faturado"),
      element("strong", "", `${decimal(line.received_quantity)} / ${decimal(line.invoiced_quantity)}`),
      element("span", "", money(line.invoiced_unit_price, line.currency)),
    );
    const delta = element("div", "delta");
    delta.append(
      element("small", "", "Deltas"),
      element("strong", "", `Qtd. ${decimal(line.quantity_delta || 0)}`),
      element("span", "", `Preço ${money(line.unit_price_delta || 0, line.currency)}`),
    );
    values.append(purchase, received, delta);
    const reasons = element("ul", "matching-reasons");
    if (line.reasons.length) {
      line.reasons.forEach((reason) => reasons.append(element("li", "", reasonLabels[reason] || reason)));
    } else {
      reasons.append(element("li", "matching-reason-ok", "Dentro das tolerâncias configuradas"));
    }
    card.append(heading, values, reasons);
    return card;
  }

  function renderWorkflow() {
    const card = $("matching-workflow-card");
    card.hidden = !workflow;
    if (!workflow) return;
    $("matching-workflow-title").textContent =
      workflow.status === "APPROVED" ? "Override aprovado" : workflow.status === "REJECTED" ? "Override rejeitado" : "Alçada em análise";
    const active = workflow.steps.find((step) => step.status === "ACTIVE");
    $("matching-workflow-meta").textContent = active
      ? `${active.name} · ${money(workflow.discrepancy_amount)} · workflow v${workflow.version}`
      : `${money(workflow.discrepancy_amount)} · decisão ${statusLabels[workflow.status] || workflow.status}`;
    $("matching-workflow-actions").hidden = !active || !can("workflow.approval.decide");
  }

  function renderDetail() {
    if (!selected) return;
    const session = selected.session;
    const snapshot = session.snapshot;
    $("matching-dossier-empty").hidden = true;
    $("matching-dossier-content").hidden = false;
    $("matching-dossier-title").textContent = `Sessão #${shortId(session.id)}`;
    $("matching-dossier-meta").textContent = `${session.id} · ETag v${session.version}`;
    $("matching-dossier-status").replaceWith(statusBadge(session.status));
    const statusNode = $("matching-dossier-content").querySelector(".matching-dossier-heading .status");
    statusNode.id = "matching-dossier-status";
    $("matching-triad").replaceChildren(
      sourceCard("purchase", "M6 · PEDIDO", snapshot.purchase_order, snapshot.purchase_order_total_amount, snapshot.currency),
      sourceCard("fiscal", "M11 · NOTA", snapshot.fiscal_documents[0], snapshot.invoiced_total_amount, snapshot.currency),
      sourceCard("finance", "M12 · OBRIGAÇÃO", snapshot.provisional_entry, snapshot.obligation_amount, snapshot.currency),
    );
    const mismatchCount = session.lines.filter((line) => line.result_status && line.result_status !== "MATCHED").length;
    $("matching-delta-summary").textContent = session.report_status
      ? `${mismatchCount} divergência(s) em ${session.lines.length} linha(s) · tolerância preço ${session.tolerance.unit_price_variance_percentage}% · quantidade ${session.tolerance.quantity_variance_percentage}%`
      : "Snapshot congelado. Execute a conferência determinística para calcular os deltas.";
    $("matching-delta-summary").dataset.result = session.report_status || "PENDING";
    $("matching-line-cards").replaceChildren(...session.lines.map(renderLine));
    $("matching-audit-list").replaceChildren(
      ...selected.audit_history.map((entry) => {
        const item = element("li", "matching-audit-entry");
        item.append(
          element("strong", "", `${entry.from_status || "INÍCIO"} → ${entry.to_status}`),
          element("span", "mono", `v${entry.aggregate_version} · ${new Date(entry.occurred_at).toLocaleString("pt-BR")}`),
        );
        return item;
      }),
    );
    $("matching-execute").hidden = session.status !== "PENDING" || !can("procurement.matching.execute");
    $("matching-override-form").hidden =
      session.status !== "DISCREPANCY_DETECTED" || !can("procurement.matching.execute") || Boolean(workflow);
    renderWorkflow();
    renderQueue();
  }

  function showError(error) {
    notice(error.message);
  }

  async function load() {
    const { company } = context();
    if (!company || !can("procurement.matching.read")) return;
    const status = $("matching-status-filter").value;
    const endpoint = exceptionsOnly ? "procurement/matching-sessions/exceptions" : "procurement/matching-sessions";
    const result = await api(
      `${endpoint}?company_id=${company}&page_size=50${status && !exceptionsOnly ? `&status=${status}` : ""}`,
    );
    sessions = result.data;
    renderQueue();
    if (selected && sessions.some((item) => item.id === selected.session.id)) {
      await openSession(selected.session.id);
    }
  }

  async function openSession(id) {
    selected = await api(`procurement/matching-sessions/${id}?company_id=${context().company}`);
    workflow = null;
    renderDetail();
  }

  async function executeSelected() {
    if (!selected) return;
    const response = await api(
      `procurement/matching-sessions/${selected.session.id}/execute?company_id=${context().company}`,
      { method: "POST", version: selected.session.version, key: crypto.randomUUID() },
    );
    notice(response.session.status === "MATCHED" ? "Conferência concluída sem divergências." : "Conferência concluída com divergências explicáveis.");
    await load();
    await openSession(response.session.id);
  }

  async function requestOverride() {
    if (!selected) return;
    const response = await api(
      `procurement/matching-sessions/${selected.session.id}/override?company_id=${context().company}`,
      {
        method: "POST",
        version: selected.session.version,
        key: crypto.randomUUID(),
        body: { justification: $("matching-override-justification").value },
      },
    );
    selected = { session: response.session, audit_history: selected.audit_history };
    workflow = response.workflow;
    notice("Override encaminhado para a alçada M22.");
    renderDetail();
  }

  async function decideOverride(decision) {
    if (!selected || !workflow) return;
    const active = workflow.steps.find((step) => step.status === "ACTIVE");
    if (!active) throw new Error("Não há etapa ativa para decisão.");
    const response = await api(
      `procurement/matching-sessions/${selected.session.id}/override/decide?company_id=${context().company}`,
      {
        method: "POST",
        version: selected.session.version,
        key: crypto.randomUUID(),
        body: {
          workflow_instance_id: workflow.id,
          workflow_step_instance_id: active.id,
          workflow_expected_version: workflow.version,
          decision,
          reason: decision === "APPROVE" ? "Alçada aprovada com base no dossiê de evidências." : "Override rejeitado após análise das evidências.",
        },
      },
    );
    selected = { session: response.session, audit_history: selected.audit_history };
    workflow = response.workflow;
    notice(decision === "APPROVE" ? "Decisão de alçada registrada." : "Override rejeitado.");
    renderDetail();
    await load();
  }

  function show() {
    const visible = can("procurement.matching.read");
    $("matching-cockpit").hidden = !visible;
    $("matching-create-disclosure").hidden = !can("procurement.matching.execute");
    return visible ? load() : Promise.resolve();
  }

  $("matching-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const response = await api("procurement/matching-sessions", {
        method: "POST",
        key: crypto.randomUUID(),
        body: {
          company_id: context().company,
          purchase_order_id: $("matching-purchase-order-id").value,
          goods_receipt_ids: [$("matching-goods-receipt-id").value],
          inbound_fiscal_document_ids: [$("matching-inbound-document-id").value],
          provisional_entry_id: $("matching-provisional-entry-id").value,
          payable_id: null,
          tolerance: {
            unit_price_variance_percentage: $("matching-price-tolerance").value,
            quantity_variance_percentage: $("matching-quantity-tolerance").value,
            rounding_absolute_limit: $("matching-rounding-tolerance").value,
            version: 1,
          },
          lines: [{
            match_key: $("matching-match-key").value,
            purchase_order_item_id: $("matching-purchase-item-id").value,
            goods_receipt_item_id: $("matching-receipt-item-id").value,
            fiscal_document_item_id: $("matching-fiscal-item-id").value,
          }],
        },
      });
      notice("Sessão de matching criada com snapshot imutável.");
      $("matching-create-disclosure").open = false;
      await load();
      await openSession(response.id);
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  });

  $("matching-status-filter").addEventListener("change", () => load().catch(showError));
  $("matching-exceptions-toggle").addEventListener("click", () => {
    exceptionsOnly = !exceptionsOnly;
    $("matching-exceptions-toggle").setAttribute("aria-pressed", String(exceptionsOnly));
    $("matching-exceptions-toggle").textContent = exceptionsOnly ? "Todas as sessões" : "Só divergências";
    load().catch(showError);
  });
  $("matching-execute").addEventListener("click", () => executeSelected().catch(showError));
  $("matching-override-form").addEventListener("submit", (event) => {
    event.preventDefault();
    requestOverride().catch(showError);
  });
  $("matching-override-approve").addEventListener("click", () => decideOverride("APPROVE").catch(showError));
  $("matching-override-reject").addEventListener("click", () => decideOverride("REJECT").catch(showError));

  return { load, reset, show };
}
