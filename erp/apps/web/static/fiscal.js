const $ = (id) => document.getElementById(id);

const labels = {
  DRAFT: "Rascunho",
  ISSUING: "Em transmissão",
  AUTHORIZED: "Autorizado",
  REJECTED: "Rejeitado",
  DENIED: "Denegado",
  CANCELLED: "Cancelado",
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
    clearPreview();
    $("fiscal-document-rows").replaceChildren();
    $("fiscal-history").replaceChildren();
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

  async function load() {
    const result = await api(`fiscal/documents?company_id=${context().company}&page=1&page_size=50`);
    documents = result.data;
    if (selected) selected = documents.find((item) => item.id === selected.id) || null;
    renderList();
    if (selected) select(selected);
  }

  async function show() {
    enter();
    $("fiscal").hidden = false;
    await load();
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
