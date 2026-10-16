import { mountMatching } from "./matching.js";

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
  RECEIVED: "Recebido",
  INSPECTED: "Inspecionado",
  POSTED: "Lançado no estoque",
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
  let suppliers = [], requisitions = [], orders = [], receipts = [];
  const matching = mountMatching({ api, context, notice });

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
    receipts = [];
    matching.reset();
    ["procurement-supplier-rows", "procurement-requisition-rows", "procurement-order-rows", "procurement-receipt-cards"].forEach(
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
    $("procurement-receipt-order").replaceChildren(
      new Option("Selecione um pedido emitido", ""),
      ...orders
        .filter((order) => ["ISSUED", "PARTIALLY_RECEIVED"].includes(order.status))
        .map((order) => new Option(order.number, order.id)),
    );
  }

  function receiptAction(label, action) {
    const button = document.createElement("button");
    button.className = "quiet";
    button.textContent = label;
    button.addEventListener("click", () => action().catch((error) => notice(error.message)));
    return button;
  }

  function renderReceipts() {
    $("procurement-receipt-count").textContent = String(receipts.length);
    $("procurement-receipt-empty").hidden = receipts.length > 0;
    $("procurement-receipt-cards").replaceChildren(
      ...receipts.map((receipt) => {
        const card = document.createElement("article");
        card.className = "receipt-card";
        const heading = document.createElement("div");
        heading.className = "receipt-card-heading";
        const title = document.createElement("strong");
        title.textContent = receipt.number;
        heading.append(title, badge(receipt.status));
        const facts = document.createElement("p");
        facts.className = "receipt-facts mono";
        facts.textContent = `${receipt.items.length} item(ns) · v${receipt.version}`;
        const actions = document.createElement("div");
        actions.className = "receipt-actions";
        if (receipt.status === "DRAFT") {
          actions.append(receiptAction("Confirmar chegada", () => mutateReceipt(receipt, "receive", {})));
        } else if (receipt.status === "RECEIVED") {
          actions.append(receiptAction("Aprovar inspeção M17", () => inspectReceipt(receipt)));
        } else if (receipt.status === "INSPECTED") {
          actions.append(receiptAction("Postar no estoque M5", () => mutateReceipt(receipt, "post-to-inventory")));
        }
        card.append(heading, facts, actions);
        return card;
      }),
    );
  }

  async function load() {
    const { company } = context();
    if (!company) return;
    const empty = { data: [] };
    const [supplierPage, requisitionPage, orderPage, receiptPage] = await Promise.all([
      can("procurement.supplier.read") ? api(`procurement/suppliers?company_id=${company}&page_size=100`) : empty,
      can("procurement.requisition.read") ? api(`procurement/requisitions?company_id=${company}&page_size=100`) : empty,
      can("procurement.order.read") ? api(`procurement/purchase-orders?company_id=${company}&page_size=100`) : empty,
      can("procurement.receipt.read") ? api(`procurement/goods-receipts?company_id=${company}&page_size=100`) : empty,
    ]);
    suppliers = supplierPage.data;
    requisitions = requisitionPage.data;
    orders = orderPage.data;
    receipts = receiptPage.data;
    renderSuppliers();
    renderRequisitions();
    renderOrders();
    renderReceipts();
    await matching.show();
  }

  async function show() {
    enter();
    notice("");
    $("procurement").hidden = false;
    $("procurement-supplier-form").hidden = !can("procurement.supplier.manage");
    $("procurement-requisition-form").hidden = !can("procurement.requisition.manage");
    $("procurement-order-form").hidden = !can("procurement.order.manage");
    $("procurement-receipt-form").hidden = !can("procurement.receipt.manage");
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

  async function mutateReceipt(receipt, action, body) {
    await api(
      `procurement/goods-receipts/${receipt.id}/${action}?company_id=${context().company}`,
      { method: "POST", version: receipt.version, key: crypto.randomUUID(), body },
    );
    notice(action === "post-to-inventory" ? "Saldo físico atualizado no M5." : "Etapa do recebimento concluída.");
    await load();
  }

  async function inspectReceipt(receipt) {
    const item = receipt.items[0];
    return mutateReceipt(receipt, "inspect", {
      decisions: [{
        receipt_item_id: item.id,
        inspection_id: crypto.randomUUID(),
        disposition: "APPROVE",
        approved_quantity: item.received_quantity,
        rejected_quantity: "0",
        quarantine_quantity: "0",
      }],
    });
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

  $("procurement-receipt-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const order = orders.find((item) => item.id === $("procurement-receipt-order").value);
      if (!order) throw new Error("Selecione um pedido emitido.");
      await api("procurement/goods-receipts", {
        method: "POST",
        key: crypto.randomUUID(),
        body: {
          company_id: context().company,
          number: $("procurement-receipt-number").value,
          purchase_order_id: order.id,
          warehouse_id: $("procurement-receipt-warehouse").value,
          tolerance_percentage: "0",
          items: [{
            purchase_order_item_id: order.items[0].id,
            received_quantity: $("procurement-receipt-quantity").value,
            specification_conforms: true,
            lot_reference: $("procurement-receipt-lot").value || null,
          }],
        },
      });
      event.target.reset();
      notice("Conferência cega registrada.");
      await load();
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  return { hide, load, reset, show };
}
