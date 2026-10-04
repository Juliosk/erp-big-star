const $ = (id) => document.getElementById(id);

const statusLabels = {
  ACTIVE: "Ativo",
  INACTIVE: "Inativo",
  BLOCKED: "Bloqueado",
  DRAFT: "Rascunho",
  SUBMITTED: "Em aprovação",
  APPROVED: "Aprovado",
  REJECTED: "Rejeitado",
  CANCELLED: "Cancelado",
  PENDING_APPROVAL: "Em aprovação",
  ISSUED: "Emitido",
  PARTIALLY_RECEIVED: "Recebido parcialmente",
  COMPLETED: "Concluído",
};

const money = (value, currency = "BRL") =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(
    Number(value),
  );

function cell(value, className = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function badge(status) {
  const value = document.createElement("span");
  value.className = `status ${status}`;
  value.textContent = statusLabels[status] || status;
  return value;
}

export function mountProcurement({ api, context, notice, enter }) {
  let suppliers = [], requisitions = [], orders = [];

  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("procurement").hidden = true;
    $("procurement-nav").removeAttribute("aria-current");
  }

  function reset() {
    hide();
    suppliers = [];
    requisitions = [];
    orders = [];
    ["procurement-supplier-rows", "procurement-requisition-rows", "procurement-order-rows"].forEach(
      (id) => $(id).replaceChildren(),
    );
  }

  function renderSuppliers() {
    $("procurement-supplier-count").textContent = String(suppliers.length);
    $("procurement-supplier-empty").hidden = suppliers.length > 0;
    $("procurement-supplier-rows").replaceChildren(
      ...suppliers.map((supplier) => {
        const row = document.createElement("tr");
        const identity = document.createElement("td");
        const strong = document.createElement("strong");
        const small = document.createElement("small");
        strong.textContent = supplier.legal_name;
        small.textContent = `${supplier.identity_kind} · ${supplier.identity_value}`;
        identity.append(strong, small);
        const status = document.createElement("td");
        status.append(badge(supplier.status));
        row.append(identity, cell(supplier.sites.length), status);
        return row;
      }),
    );
    const options = suppliers
      .filter((supplier) => supplier.status === "ACTIVE")
      .map((supplier) => new Option(supplier.legal_name, supplier.id));
    $("procurement-order-supplier").replaceChildren(
      new Option("Selecione o fornecedor", ""),
      ...options,
    );
  }

  function renderRequisitions() {
    $("procurement-requisition-count").textContent = String(requisitions.length);
    $("procurement-requisition-empty").hidden = requisitions.length > 0;
    $("procurement-requisition-rows").replaceChildren(
      ...requisitions.map((requisition) => {
        const row = document.createElement("tr");
        const state = document.createElement("td");
        const action = document.createElement("td");
        state.append(badge(requisition.status));
        if (requisition.status === "DRAFT" && can("procurement.requisition.manage")) {
          const button = document.createElement("button");
          button.className = "quiet";
          button.textContent = "Enviar para aprovação";
          button.addEventListener("click", () =>
            submitRequisition(requisition).catch((error) => notice(error.message)),
          );
          action.append(button);
        }
        row.append(
          cell(requisition.number, "mono"),
          cell(requisition.urgency),
          cell(requisition.deadline),
          state,
          action,
        );
        return row;
      }),
    );
    $("procurement-order-requisition").replaceChildren(
      new Option("Selecione a requisição aprovada", ""),
      ...requisitions
        .filter((item) => item.status === "APPROVED")
        .map((item) => new Option(item.number, item.id)),
    );
  }

  function renderOrders() {
    $("procurement-order-count").textContent = String(orders.length);
    $("procurement-order-empty").hidden = orders.length > 0;
    $("procurement-order-rows").replaceChildren(
      ...orders.map((order) => {
        const row = document.createElement("tr");
        const state = document.createElement("td");
        const action = document.createElement("td");
        state.append(badge(order.status));
        if (order.status === "DRAFT" && can("procurement.order.manage")) {
          const button = document.createElement("button");
          button.className = "quiet";
          button.textContent = "Solicitar aprovação M22";
          button.addEventListener("click", () =>
            submitOrder(order).catch((error) => notice(error.message)),
          );
          action.append(button);
        }
        row.append(
          cell(order.number, "mono"),
          cell(money(order.total_amount, order.currency)),
          state,
          cell(`v${order.version}`, "mono"),
          action,
        );
        return row;
      }),
    );
  }

  async function load() {
    const { company } = context();
    if (!company) return;
    const [supplierPage, requisitionPage, orderPage] = await Promise.all([
      api(`procurement/suppliers?company_id=${company}&page_size=100`),
      api(`procurement/requisitions?company_id=${company}&page_size=100`),
      api(`procurement/purchase-orders?company_id=${company}&page_size=100`),
    ]);
    suppliers = supplierPage.data;
    requisitions = requisitionPage.data;
    orders = orderPage.data;
    renderSuppliers();
    renderRequisitions();
    renderOrders();
  }

  async function show() {
    enter();
    notice("");
    $("procurement").hidden = false;
    $("procurement-supplier-form").hidden = !can("procurement.supplier.manage");
    $("procurement-requisition-form").hidden = !can("procurement.requisition.manage");
    $("procurement-order-form").hidden = !can("procurement.order.manage");
    await load();
  }

  async function submitRequisition(requisition) {
    await api(
      `procurement/requisitions/${requisition.id}/submit?company_id=${context().company}`,
      { method: "POST", version: requisition.version },
    );
    notice("Requisição enviada para aprovação.");
    await load();
  }

  async function submitOrder(order) {
    await api(
      `procurement/purchase-orders/${order.id}/submit?company_id=${context().company}`,
      { method: "POST", version: order.version },
    );
    notice("Aprovação formal solicitada ao M22.");
    await load();
  }

  $("procurement-refresh").addEventListener("click", () =>
    load().catch((error) => notice(error.message)),
  );

  $("procurement-supplier-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      await api("procurement/suppliers", {
        method: "POST",
        body: {
          company_id: context().company,
          kind: "COMPANY",
          identity_kind: "CNPJ",
          identity_value: $("procurement-supplier-document").value,
          identity_country_code: "BR",
          legal_name: $("procurement-supplier-name").value,
          trade_name: $("procurement-supplier-trade-name").value || null,
          sites: [],
        },
      });
      event.target.reset();
      notice("Fornecedor cadastrado.");
      await load();
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  $("procurement-requisition-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      await api("procurement/requisitions", {
        method: "POST",
        body: {
          company_id: context().company,
          number: $("procurement-requisition-number").value,
          cost_center_id: $("procurement-cost-center").value,
          justification: $("procurement-justification").value,
          items: [
            {
              product_id: $("procurement-product-id").value,
              quantity: $("procurement-quantity").value,
              unit_of_measure: "UN",
              needed_by: $("procurement-needed-by").value,
              urgency: $("procurement-urgency").value,
              specification: $("procurement-specification").value,
            },
          ],
        },
      });
      event.target.reset();
      notice("Requisição de compra aberta.");
      await load();
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  $("procurement-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const requisition = requisitions.find(
        (item) => item.id === $("procurement-order-requisition").value,
      );
      if (!requisition) throw new Error("Selecione uma requisição aprovada.");
      await api("procurement/purchase-orders", {
        method: "POST",
        body: {
          company_id: context().company,
          number: $("procurement-order-number").value,
          source_requisition_id: requisition.id,
          supplier_id: $("procurement-order-supplier").value,
          currency: "BRL",
          payment_terms_code: "30D",
          payment_terms_description: "Trinta dias",
          installment_days: [30],
          items: [
            {
              requisition_item_id: requisition.items[0].id,
              quantity: requisition.items[0].quantity,
              unit_price: $("procurement-order-unit-price").value,
            },
          ],
        },
      });
      event.target.reset();
      notice("Pedido de compra criado.");
      await load();
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  return { hide, load, reset, show };
}
