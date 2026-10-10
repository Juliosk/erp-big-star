const $ = (id) => document.getElementById(id);

const labels = {
  DRAFT: "Rascunho",
  ISSUING: "Em transmissão",
  AUTHORIZED: "Autorizado",
  REJECTED: "Rejeitado",
  DENIED: "Denegado",
  CANCELLED: "Cancelado",
};
const mdeLabels = {
  PENDING: "Pendente",
  ACKNOWLEDGED: "Ciência registrada",
  CONFIRMED: "Operação confirmada",
  UNKNOWN_OPERATION: "Operação desconhecida",
  OPERATION_NOT_PERFORMED: "Operação não realizada",
};
const issueLabels = {
  SUPPLIER_MISMATCH: "Fornecedor divergente",
  LINE_MAPPING_MISMATCH: "Amarração incompleta",
  QUANTITY_MISMATCH: "Quantidade divergente",
  UNIT_PRICE_MISMATCH: "Preço divergente",
  FISCAL_TOTAL_MISMATCH: "Total fiscal divergente",
  SPECIFICATION_MISMATCH: "Especificação divergente",
  INSPECTION_NOT_APPROVED: "Inspeção não aprovada",
};

function badge(status) {
  const element = document.createElement("span");
  element.className = `status ${status}`;
  element.textContent = labels[status] || status;
  return element;
}

function cell(value, className = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

const zeroTax = (taxCode) => ({
  tax_code: taxCode,
  taxable_base: "0.00",
  rate: "0.00",
  amount: "0.00",
});

export function mountFiscal({ api, context, notice, enter }) {
  let documents = [];
  let selected = null;
  let inboundDocuments = [];
  let selectedInbound = null;
  let inspectedReceipts = [];
  let previewUrl = "";
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("fiscal").hidden = true;
    $("fiscal-nav").removeAttribute("aria-current");
  }

  function clearPreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = "";
    $("fiscal-danfe-preview").removeAttribute("src");
    $("fiscal-danfe-preview").hidden = true;
  }

  function reset() {
    hide();
    documents = [];
    selected = null;
    inboundDocuments = [];
    selectedInbound = null;
    inspectedReceipts = [];
    clearPreview();
    $("fiscal-document-rows").replaceChildren();
    $("fiscal-history").replaceChildren();
    $("fiscal-inbound-rows").replaceChildren();
    $("fiscal-inbound-item-rows").replaceChildren();
    $("fiscal-mde-history").replaceChildren();
    $("fiscal-line-mappings").replaceChildren();
    $("fiscal-reconciliation-issues").replaceChildren();
    $("fiscal-inbound-detail").hidden = true;
    $("fiscal-reconciliation-form").hidden = true;
    $("fiscal-reconciliation-report").hidden = true;
  }

  function switchView(view) {
    const inbound = view === "inbound";
    $("fiscal-outbound-view").hidden = inbound;
    document.querySelector(".fiscal-rail").hidden = inbound;
    $("fiscal-inbound-view").hidden = !inbound;
    $("fiscal-outbound-tab").setAttribute("aria-selected", String(!inbound));
    $("fiscal-inbound-tab").setAttribute("aria-selected", String(inbound));
    $("fiscal-outbound-tab").classList.toggle("secondary", inbound);
    $("fiscal-inbound-tab").classList.toggle("secondary", !inbound);
  }

  function renderRail(status) {
    document.querySelectorAll("[data-fiscal-stage]").forEach((item) => {
      item.classList.toggle("active", item.dataset.fiscalStage === status);
    });
  }

  function renderList() {
    $("fiscal-document-count").textContent = String(documents.length);
    $("fiscal-empty").hidden = documents.length > 0;
    $("fiscal-document-rows").replaceChildren(
      ...documents.map((document) => {
        const row = documentNode("tr");
        row.tabIndex = 0;
        row.className = selected?.id === document.id ? "selected" : "";
        row.addEventListener("click", () => select(document));
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter") select(document);
        });
        const status = documentNode("td");
        status.append(badge(document.status));
        row.append(
          cell(`${document.model === "55" ? "NF-e" : "NFC-e"} ${document.series}/${document.number}`, "mono"),
          cell(document.recipient.legal_name),
          status,
          cell(`v${document.version}`, "mono"),
        );
        return row;
      }),
    );
  }

  function select(document) {
    selected = document;
    clearPreview();
    renderList();
    renderRail(document.status);
    $("fiscal-selected-title").textContent = `${document.model === "55" ? "NF-e" : "NFC-e"} ${document.series}/${document.number}`;
    $("fiscal-selected-status").className = `status ${document.status}`;
    $("fiscal-selected-status").textContent = labels[document.status] || document.status;
    $("fiscal-selected-meta").textContent = document.authorization_protocol
      ? `Protocolo ${document.authorization_protocol} · Chave ${document.access_key}`
      : document.rejection_reason || `Empresa ${document.company_id} · versão ${document.version}`;
    $("fiscal-actions").hidden = false;
    $("fiscal-issue").hidden = document.status !== "DRAFT" || !can("fiscal.nfe.issue");
    $("fiscal-process").hidden = document.status !== "ISSUING" || !can("fiscal.nfe.issue");
    $("fiscal-danfe").hidden = !["AUTHORIZED", "CANCELLED"].includes(document.status);
    $("fiscal-xml").hidden = !["AUTHORIZED", "CANCELLED"].includes(document.status);
    $("fiscal-cancel").hidden = document.status !== "AUTHORIZED" || !can("fiscal.nfe.cancel");
    $("fiscal-history").replaceChildren(
      ...document.sefaz_history.map((entry, index) => {
        const item = documentNode("li");
        const number = documentNode("span");
        number.className = "workflow-step-number";
        number.textContent = String(index + 1).padStart(2, "0");
        const detail = documentNode("div");
        const title = documentNode("strong");
        const meta = documentNode("small");
        title.textContent = `${entry.status_code} · ${entry.message}`;
        meta.textContent = new Date(entry.occurred_at).toLocaleString("pt-BR");
        detail.append(title, meta);
        item.append(number, detail);
        return item;
      }),
    );
  }

  function money(value) {
    return Number(value).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  }

  function renderInboundSummary() {
    const counts = inboundDocuments.reduce(
      (result, document) => {
        result[document.mde_status] = (result[document.mde_status] || 0) + 1;
        return result;
      },
      {},
    );
    $("fiscal-inbound-count").textContent = String(inboundDocuments.length);
    $("fiscal-mde-pending").textContent = String(counts.PENDING || 0);
    $("fiscal-mde-acknowledged").textContent = String(
      counts.ACKNOWLEDGED || 0,
    );
    $("fiscal-mde-confirmed").textContent = String(counts.CONFIRMED || 0);
    $("fiscal-mde-exception").textContent = String(
      (counts.UNKNOWN_OPERATION || 0) +
        (counts.OPERATION_NOT_PERFORMED || 0),
    );
  }

  function renderInboundList() {
    renderInboundSummary();
    $("fiscal-inbound-empty").hidden = inboundDocuments.length > 0;
    $("fiscal-inbound-rows").replaceChildren(
      ...inboundDocuments.map((document) => {
        const row = documentNode("tr");
        row.tabIndex = 0;
        row.className = selectedInbound?.id === document.id ? "selected" : "";
        row.addEventListener("click", () =>
          selectInbound(document.id).catch((error) => notice(error.message)),
        );
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter")
            selectInbound(document.id).catch((error) => notice(error.message));
        });
        const state = documentNode("td");
        const stateBadge = documentNode("span");
        stateBadge.className = `status ${document.mde_status}`;
        stateBadge.textContent = mdeLabels[document.mde_status] || document.mde_status;
        state.append(stateBadge);
        row.append(
          cell(`${document.series}/${document.number}`, "mono"),
          cell(document.supplier.legal_name),
          state,
          cell(money(document.total_amount), "mono"),
        );
        return row;
      }),
    );
  }

  function renderInboundDetail() {
    const document = selectedInbound;
    $("fiscal-inbound-detail").hidden = !document;
    $("fiscal-reconciliation-form").hidden = !document;
    if (!document) return;
    $("fiscal-inbound-title").textContent = `NF-e ${document.series}/${document.number}`;
    $("fiscal-inbound-status").className = `status ${document.mde_status}`;
    $("fiscal-inbound-status").textContent =
      mdeLabels[document.mde_status] || document.mde_status;
    $("fiscal-inbound-meta").textContent =
      `Chave ${document.access_key} · protocolo ${document.authorization_protocol} · versão ${document.version}`;
    $("fiscal-inbound-supplier").textContent =
      `${document.supplier.legal_name} · ${document.supplier.tax_id}`;
    $("fiscal-inbound-products-total").textContent = money(
      document.products_amount,
    );
    $("fiscal-inbound-total").textContent = money(document.total_amount);
    $("fiscal-inbound-item-rows").replaceChildren(
      ...document.items.map((item) => {
        const row = documentNode("tr");
        row.append(
          cell(String(item.line_number).padStart(2, "0"), "mono"),
          cell(`${item.supplier_code} · ${item.description}`),
          cell(`${item.quantity} ${item.unit_of_measure}`, "mono"),
          cell(money(item.unit_price), "mono"),
        );
        return row;
      }),
    );
    $("fiscal-mde-history").replaceChildren(
      ...document.manifestations.map((event, index) => {
        const item = documentNode("li");
        const number = documentNode("span");
        number.className = "workflow-step-number";
        number.textContent = String(index + 1).padStart(2, "0");
        const detail = documentNode("div");
        const title = documentNode("strong");
        const meta = documentNode("small");
        title.textContent = `${event.event_type} · protocolo ${event.protocol}`;
        meta.textContent = new Date(event.registered_at).toLocaleString("pt-BR");
        detail.append(title, meta);
        item.append(number, detail);
        return item;
      }),
    );
    $("fiscal-mde-form").hidden =
      !can("fiscal.inbound.manage") ||
      ["CONFIRMED", "UNKNOWN_OPERATION", "OPERATION_NOT_PERFORMED"].includes(
        document.mde_status,
      );
  }

  async function loadInbound() {
    const result = await api(
      `fiscal/inbound-documents?company_id=${context().company}&page=1&page_size=50`,
    );
    inboundDocuments = result.items;
    if (selectedInbound)
      selectedInbound =
        inboundDocuments.find((item) => item.id === selectedInbound.id) || null;
    renderInboundList();
    if (selectedInbound) renderInboundDetail();
  }

  async function selectInbound(documentId) {
    selectedInbound = await api(
      `fiscal/inbound-documents/${documentId}?company_id=${context().company}`,
    );
    renderInboundList();
    renderInboundDetail();
    await Promise.all([loadInspectedReceipts(), loadReconciliation()]);
  }

  async function loadInspectedReceipts() {
    const result = await api(
      `procurement/goods-receipts?company_id=${context().company}&status=INSPECTED&page=1&page_size=100`,
    );
    inspectedReceipts = result.data;
    $("fiscal-receipt").replaceChildren(
      new Option("Selecione um recebimento", ""),
      ...inspectedReceipts.map(
        (receipt) =>
          new Option(
            `${receipt.number} · ${receipt.items.length} item(ns) · v${receipt.version}`,
            receipt.id,
          ),
      ),
    );
    $("fiscal-line-mappings").replaceChildren();
  }

  function renderMappings() {
    const receipt = inspectedReceipts.find(
      (item) => item.id === $("fiscal-receipt").value,
    );
    $("fiscal-line-mappings").replaceChildren();
    if (!receipt || !selectedInbound) return;
    selectedInbound.items.forEach((fiscalItem) => {
      const line = documentNode("div");
      line.className = "line-mapping";
      const description = documentNode("div");
      const title = documentNode("strong");
      const meta = documentNode("small");
      title.textContent = `Linha ${fiscalItem.line_number} · ${fiscalItem.supplier_code}`;
      meta.textContent = `${fiscalItem.quantity} ${fiscalItem.unit_of_measure} · ${fiscalItem.description}`;
      description.append(title, meta);
      const select = documentNode("select");
      select.required = true;
      select.dataset.inboundLine = String(fiscalItem.line_number);
      select.setAttribute(
        "aria-label",
        `Item físico para linha fiscal ${fiscalItem.line_number}`,
      );
      select.append(
        new Option("Escolha o item físico conferido", ""),
        ...receipt.items.map((item) => {
          const inspection = receipt.inspection_results.find(
            (result) => result.receipt_item_id === item.id,
          );
          return new Option(
            `${item.product_id} · aprovado ${inspection?.approved_quantity || "0"}`,
            item.id,
          );
        }),
      );
      line.append(description, select);
      $("fiscal-line-mappings").append(line);
    });
  }

  function renderReconciliation(report) {
    $("fiscal-reconciliation-report").hidden = false;
    $("fiscal-reconciliation-status").className =
      `reconciliation-signal ${report.status}`;
    $("fiscal-reconciliation-status").textContent =
      report.status === "POSTED" ? "Conciliado e lançado" : "Divergências encontradas";
    $("fiscal-financial-flag").textContent = report.financial_blocked
      ? "Contas a pagar bloqueado"
      : "Financeiro liberado";
    $("fiscal-financial-flag").classList.toggle(
      "blocked",
      report.financial_blocked,
    );
    $("fiscal-physical-flag").textContent = report.physical_pending
      ? "Pendência física / devolução"
      : "Físico conciliado";
    $("fiscal-physical-flag").classList.toggle(
      "blocked",
      report.physical_pending,
    );
    $("fiscal-reconciliation-issues").replaceChildren(
      ...report.issues.map((issue) => {
        const item = documentNode("li");
        const title = documentNode("strong");
        const detail = documentNode("small");
        title.textContent = issueLabels[issue.kind] || issue.kind;
        detail.textContent = `${issue.message}${issue.expected !== null ? ` · esperado ${issue.expected}` : ""}${issue.actual !== null ? ` · encontrado ${issue.actual}` : ""}`;
        item.append(title, detail);
        return item;
      }),
    );
    if (!report.issues.length) {
      const item = documentNode("li");
      const title = documentNode("strong");
      title.textContent = "Sem inconsistências";
      item.append(title, document.createTextNode(" Linhas fiscais e físicas coincidem."));
      $("fiscal-reconciliation-issues").append(item);
    }
    $("fiscal-reconciliation-meta").textContent =
      `${report.inventory_transaction_ids.length} lançamento(s) no ledger M5 · conciliado em ${new Date(report.reconciled_at).toLocaleString("pt-BR")}`;
    $("fiscal-reconciliation-form").hidden = true;
  }

  async function loadReconciliation() {
    $("fiscal-reconciliation-report").hidden = true;
    $("fiscal-reconciliation-status").className = "reconciliation-signal";
    $("fiscal-reconciliation-status").textContent = "Pronto para conferir";
    $("fiscal-reconciliation-form").hidden = !selectedInbound;
    if (!selectedInbound) return;
    try {
      renderReconciliation(
        await api(
          `fiscal/inbound-documents/${selectedInbound.id}/reconcile?company_id=${context().company}`,
        ),
      );
    } catch (error) {
      if (error.code !== "RESOURCE_NOT_FOUND") throw error;
    }
  }

  async function load() {
    if (can("fiscal.nfe.read")) {
      const result = await api(
        `fiscal/documents?company_id=${context().company}&page=1&page_size=50`,
      );
      documents = result.data;
      if (selected)
        selected = documents.find((item) => item.id === selected.id) || null;
      renderList();
      if (selected) select(selected);
    }
    if (can("fiscal.inbound.read")) await loadInbound();
  }

  async function show() {
    enter();
    $("fiscal").hidden = false;
    $("fiscal-outbound-tab").hidden = !can("fiscal.nfe.read");
    $("fiscal-inbound-tab").hidden = !can("fiscal.inbound.read");
    switchView(can("fiscal.nfe.read") ? "outbound" : "inbound");
    await load();
  }

  async function uploadInbound(event) {
    const input = $("fiscal-inbound-file");
    const file = input.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024)
      throw new Error("O XML deve ter no máximo 5 MB.");
    event.submitter.disabled = true;
    try {
      const created = await api(
        `fiscal/inbound-documents/upload?company_id=${context().company}`,
        {
          method: "POST",
          raw: await file.text(),
          contentType: "application/xml",
          key: crypto.randomUUID(),
        },
      );
      input.value = "";
      notice("XML de entrada importado e validado.");
      await loadInbound();
      await selectInbound(created.id);
    } finally {
      event.submitter.disabled = false;
    }
  }

  async function manifestInbound(event) {
    const eventType = $("fiscal-mde-event").value;
    event.submitter.disabled = true;
    try {
      selectedInbound = await api(
        `fiscal/inbound-documents/${selectedInbound.id}/manifest?company_id=${context().company}`,
        {
          method: "POST",
          version: selectedInbound.version,
          key: crypto.randomUUID(),
          body: {
            event_type: eventType,
            reason:
              eventType === "210240"
                ? $("fiscal-mde-reason").value
                : null,
          },
        },
      );
      notice(`Manifestação ${eventType} registrada na SEFAZ.`);
      await loadInbound();
      renderInboundDetail();
    } finally {
      event.submitter.disabled = false;
    }
  }

  async function reconcileInbound(event) {
    const mappings = [...$("fiscal-line-mappings").querySelectorAll("select")].map(
      (select) => ({
        inbound_line_number: Number(select.dataset.inboundLine),
        receipt_item_id: select.value,
      }),
    );
    if (!mappings.length || mappings.some((item) => !item.receipt_item_id))
      throw new Error("Vincule cada linha fiscal a um item físico conferido.");
    if (new Set(mappings.map((item) => item.receipt_item_id)).size !== mappings.length)
      throw new Error("Cada item físico pode ser vinculado a somente uma linha fiscal.");
    event.submitter.disabled = true;
    try {
      const report = await api(
        `fiscal/inbound-documents/${selectedInbound.id}/reconcile?company_id=${context().company}`,
        {
          method: "POST",
          version: selectedInbound.version,
          key: crypto.randomUUID(),
          body: {
            goods_receipt_id: $("fiscal-receipt").value,
            line_mappings: mappings,
            price_tolerance: $("fiscal-price-tolerance").value,
          },
        },
      );
      renderReconciliation(report);
      notice(
        report.status === "POSTED"
          ? "Conciliação aprovada. Saldo AVAILABLE lançado no M5."
          : "Conciliação concluída com divergências. Consulte o relatório.",
      );
    } finally {
      event.submitter.disabled = false;
    }
  }

  async function create(event) {
    event.submitter.disabled = true;
    try {
      const quantity = $("fiscal-quantity").value;
      const unitPrice = $("fiscal-unit-price").value;
      const amount = (Number(quantity) * Number(unitPrice)).toFixed(2);
      const partyAddress = {
        street: "Rua de Homologação", number: "100", district: "Centro",
        city: "São Paulo", state_code: "SP", postal_code: "01001000", country_code: "BR",
      };
      const created = await api("fiscal/documents", {
        method: "POST",
        body: {
          company_id: context().company,
          model: $("fiscal-model").value,
          series: Number($("fiscal-series").value),
          number: Number($("fiscal-number").value),
          issuer: { tax_id: $("fiscal-issuer-tax-id").value, legal_name: $("fiscal-issuer-name").value, ...partyAddress },
          recipient: { tax_id: $("fiscal-recipient-tax-id").value, legal_name: $("fiscal-recipient-name").value, ...partyAddress },
          items: [{
            product_id: $("fiscal-product-id").value,
            code: $("fiscal-item-code").value,
            description: $("fiscal-item-description").value,
            ncm: "95030099", cfop: "5102", unit_of_measure: "UN",
            quantity, unit_price: unitPrice, total_amount: amount,
            taxes: { icms: zeroTax("00"), pis: zeroTax("07"), cofins: zeroTax("07"), ipi: zeroTax("53") },
          }],
        },
      });
      notice("Rascunho fiscal criado.");
      await load();
      select(documents.find((item) => item.id === created.id));
    } finally {
      event.submitter.disabled = false;
    }
  }

  async function issue() {
    selected = await api(`fiscal/documents/${selected.id}/issue?company_id=${context().company}`, {
      method: "POST", version: selected.version, key: crypto.randomUUID(),
    });
    notice("Emissão solicitada. Documento aguardando processamento SEFAZ.");
    await load();
  }

  async function processDocument() {
    selected = await api(`fiscal/documents/${selected.id}/process?company_id=${context().company}`, {
      method: "POST", version: selected.version,
      body: { contingency: $("fiscal-contingency").value },
    });
    notice(`Retorno SEFAZ processado: ${labels[selected.status] || selected.status}.`);
    await load();
  }

  async function cancel() {
    selected = await api(`fiscal/documents/${selected.id}/cancel?company_id=${context().company}`, {
      method: "POST", version: selected.version,
      body: { reason: $("fiscal-cancel-reason").value },
    });
    notice("Evento de cancelamento 110111 homologado.");
    await load();
  }

  async function danfe() {
    clearPreview();
    const blob = await api(`fiscal/documents/${selected.id}/danfe?company_id=${context().company}`, { binary: true });
    previewUrl = URL.createObjectURL(blob);
    $("fiscal-danfe-preview").src = previewUrl;
    $("fiscal-danfe-preview").hidden = false;
  }

  async function xml() {
    const blob = await api(`fiscal/documents/${selected.id}/xml?company_id=${context().company}`, { binary: true });
    const url = URL.createObjectURL(blob);
    const link = documentNode("a");
    link.href = url;
    link.download = `fiscal-${selected.number}.xml`;
    link.click();
    URL.revokeObjectURL(url);
  }

  $("fiscal-create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    create(event).catch((error) => notice(error.message));
  });
  $("fiscal-inbound-upload-form").addEventListener("submit", (event) => {
    event.preventDefault();
    uploadInbound(event).catch((error) => notice(error.message));
  });
  $("fiscal-mde-form").addEventListener("submit", (event) => {
    event.preventDefault();
    manifestInbound(event).catch((error) => notice(error.message));
  });
  $("fiscal-reconciliation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    reconcileInbound(event).catch((error) => notice(error.message));
  });
  $("fiscal-outbound-tab").addEventListener("click", () => switchView("outbound"));
  $("fiscal-inbound-tab").addEventListener("click", () => switchView("inbound"));
  $("fiscal-receipt").addEventListener("change", renderMappings);
  $("fiscal-mde-event").addEventListener("change", () => {
    const requiresReason = $("fiscal-mde-event").value === "210240";
    $("fiscal-mde-reason").disabled = !requiresReason;
    $("fiscal-mde-reason").required = requiresReason;
    if (!requiresReason) $("fiscal-mde-reason").value = "";
  });
  $("fiscal-refresh").addEventListener("click", () => load().catch((error) => notice(error.message)));
  $("fiscal-issue").addEventListener("click", () => issue().catch((error) => notice(error.message)));
  $("fiscal-process").addEventListener("click", () => processDocument().catch((error) => notice(error.message)));
  $("fiscal-cancel").addEventListener("click", () => cancel().catch((error) => notice(error.message)));
  $("fiscal-danfe").addEventListener("click", () => danfe().catch((error) => notice(error.message)));
  $("fiscal-xml").addEventListener("click", () => xml().catch((error) => notice(error.message)));

  return { hide, reset, show };
}

function documentNode(tag) {
  return document.createElement(tag);
}
