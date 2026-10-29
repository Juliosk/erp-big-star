import { mountImports } from "./imports.js";
import { mountCustomers } from "./customers.js";
import { mountInventory } from "./inventory.js";
import { mountPricing } from "./pricing.js";
import { mountWms } from "./wms.js";
import { mountWorkflow } from "./workflow.js";
import { mountSales } from "./sales.js";
import { mountProcurement } from "./procurement.js";
import { mountFiscal } from "./fiscal.js";
import { mountFinance } from "./finance.js";
import { mountTreasury } from "./treasury.js";
import { mountBankConciliation } from "./conciliation.js";
const $ = (id) => document.getElementById(id);
const labels = {
  EM_DESENVOLVIMENTO: "Em desenvolvimento",
  EM_HOMOLOGACAO: "Em homologação",
  ATIVO: "Ativo",
  FORA_DE_LINHA: "Fora de linha",
};
const errors = {
  VERSION_CONFLICT:
    "Outra alteração foi salva. Atualize o detalhe antes de tentar novamente.",
  BARCODE_CONFLICT: "Este código de barras já existe na empresa.",
  PRODUCT_IDENTIFIER_CONFLICT:
    "Código ou SKU já cadastrado. Confira os identificadores.",
  CUSTOMER_DUPLICATE_EXACT_MATCH:
    "CPF/CNPJ já cadastrado para a empresa selecionada.",
  CUSTOMER_GROUP_CONFLICT: "Grupo de clientes já cadastrado nesta empresa.",
  CUSTOMER_GROUP_MEMBER_CONFLICT: "Este cliente já pertence ao grupo.",
  CUSTOMER_MERGE_REQUEST_CONFLICT:
    "Já existe uma solicitação pendente para este par de clientes.",
  INVENTORY_NEGATIVE_BALANCE:
    "O ajuste deixaria saldo negativo. Revise quantidade, lote e depósito.",
  MINIMUM_MARGIN_VIOLATION:
    "A margem projetada está abaixo da política mínima da empresa.",
  PRICE_NOT_FOUND:
    "Nenhum preço ativo foi encontrado para o produto e lista informados.",
  STANDARD_COST_NOT_FOUND:
    "Cadastre um custo padrão provisório para simular ou resolver o preço.",
  INVALID_PRICE_LIST_VERSION_STATUS:
    "A versão da lista não está em situação compatível com esta ação.",
  PRICING_PRICE_LIST_CONFLICT:
    "Já existe uma lista de preços com este código na empresa selecionada.",
  PRICING_PRICE_LIST_VERSION_CONFLICT:
    "Outra alteração foi salva nesta versão de lista. Atualize antes de ativar.",
  PRICING_UNAVAILABLE: "Pricing indisponível nesta inicialização.",
  PRICING_RESOLUTION_UNAVAILABLE:
    "Resolução de pricing indisponível nesta inicialização.",
  PRICING_SIMULATION_UNAVAILABLE:
    "Simulação de pricing indisponível nesta inicialização.",
  PRICING_SNAPSHOTS_UNAVAILABLE:
    "Consulta de snapshots indisponível nesta inicialização.",
  WMS_BARCODE_MISMATCH:
    "Código de barras não corresponde ao produto da tarefa.",
  WMS_PACKAGE_EMPTY:
    "Adicione ao menos um item antes de verificar o pacote.",
  WMS_PACKAGE_ITEM_MISMATCH:
    "O item do pacote não corresponde à tarefa de separação.",
  WMS_PACKAGE_OVER_PACK:
    "A quantidade embalada excede a quantidade já bipada.",
  WMS_PACKAGE_STATUS_CONFLICT:
    "O pacote não está em uma situação compatível com esta ação.",
  WMS_PICKING_TASK_NOT_PICKED:
    "Bipe a tarefa antes de adicionar o item ao pacote.",
  WMS_PICKING_TASK_OVER_PICK:
    "A bipagem excede a quantidade solicitada na tarefa.",
  WMS_PICKING_WAVE_STATUS_CONFLICT:
    "A onda não está em uma situação compatível com esta ação.",
  WMS_PACKING_UNAVAILABLE: "Packing WMS indisponível nesta inicialização.",
  PERMISSION_FORBIDDEN: "Sua identidade não tem permissão para esta ação.",
  RESOURCE_NOT_FOUND: "Cadastro não encontrado na empresa selecionada.",
  INVALID_LIFECYCLE_TRANSITION:
    "Esta transição não é permitida para a situação atual.",
  AUTHENTICATION_UNAVAILABLE:
    "Configure o adapter de identidade. Em local/test, habilite DEV_AUTH_ENABLED e configure token, ator e empresas.",
  AUTHENTICATION_REQUIRED: "Token inválido ou expirado. Conecte-se novamente.",
  INVALID_BARCODE: "Código inválido. Confira o formato e o dígito verificador.",
  IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD:
    "A tentativa anterior possui dados diferentes. Revise o formulário.",
  VALIDATION_ERROR: "Confira os campos obrigatórios e seus formatos.",
  BUSINESS_VALIDATION_ERROR: "Os dados não atendem às regras do cadastro.",
  SUPPLIER_CONFLICT: "Já existe um fornecedor com este documento na empresa.",
  SOD_VIOLATION:
    "A segregação de funções impede a autoaprovação desta solicitação.",
  PAYABLE_DIVERGENCE_BLOCKED:
    "Divergências fiscais ou de compras precisam ser resolvidas antes desta ação.",
  PAYABLE_APPROVAL_REQUIRED:
    "Este título ainda depende da aprovação de alçada no M22.",
  PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED:
    "A política de alçada financeira não está configurada para esta empresa.",
  FINANCE_PAYABLE_UNAVAILABLE:
    "O serviço de contas a pagar está indisponível nesta inicialização.",
  FINANCE_TREASURY_UNAVAILABLE:
    "O serviço de tesouraria está indisponível nesta inicialização.",
  PAYMENT_BATCH_REVIEW_BLOCKED:
    "O lote possui divergências pendentes. Consulte a fila explicável antes de gerar a remessa.",
  DRY_RUN_BATCH_NOT_EXECUTABLE:
    "Este lote é somente simulação e não pode gerar uma remessa oficial.",
  FISCAL_SEFAZ_UNAVAILABLE:
    "O gateway SEFAZ não está configurado para este ambiente.",
  FISCAL_CANCELLATION_WINDOW_EXPIRED:
    "A janela legal de cancelamento deste documento expirou.",
  FISCAL_CANCELLATION_REJECTED:
    "A SEFAZ rejeitou o evento de cancelamento. Consulte o histórico.",
  FISCAL_DOCUMENT_NOT_EXPORTABLE:
    "O documento ainda não possui artefato fiscal oficial para exportação.",
  FISCAL_STORAGE_UNAVAILABLE:
    "O armazenamento fiscal está temporariamente indisponível.",
  FISCAL_INBOUND_CONFLICT:
    "Este XML de entrada já foi registrado para a empresa selecionada.",
  GOODS_RECEIPT_NOT_INSPECTED:
    "O recebimento precisa concluir a inspeção M17 antes da conciliação.",
  RECONCILIATION_ALREADY_EXISTS:
    "Esta nota fiscal já possui uma conciliação registrada.",
  RECONCILIATION_POSTING_INCOMPLETE:
    "Todos os itens conciliados precisam estar aprovados para saldo disponível.",
  UNSUPPORTED_MEDIA_TYPE: "Selecione um arquivo XML válido do fornecedor.",
};
let token = "",
  permissions = new Set(),
  company = "",
  page = 1,
  current = null,
  generation = 0,
  area = "products";
let lastCreation = { body: "", key: "" };
const can = (action) => permissions.has(`product.product.${action}`);
let customers,
  inventory,
  pricing,
  wms,
  workflow,
  sales,
  procurement,
  fiscal,
  finance,
  treasury,
  conciliation;
const imports = mountImports({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "imports";
    $("imports-nav").setAttribute("aria-current", "page");
    $("products-nav").removeAttribute("aria-current");
    $("customers-nav").removeAttribute("aria-current");
    $("inventory-nav").removeAttribute("aria-current");
    $("pricing-nav").removeAttribute("aria-current");
    $("wms-nav").removeAttribute("aria-current");
    $("workflow-nav").removeAttribute("aria-current");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent =
      "Governança / Importações";
    generation++;
    current = null;
    $("catalog").hidden = true;
    $("detail").hidden = true;
    customers?.hide();
    inventory?.hide();
    pricing?.hide();
    wms?.hide();
    workflow?.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
  },
});
customers = mountCustomers({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "customers";
    $("customers-nav").setAttribute("aria-current", "page");
    $("products-nav").removeAttribute("aria-current");
    $("imports-nav").removeAttribute("aria-current");
    $("inventory-nav").removeAttribute("aria-current");
    $("pricing-nav").removeAttribute("aria-current");
    $("wms-nav").removeAttribute("aria-current");
    $("workflow-nav").removeAttribute("aria-current");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent = "Cadastros / Clientes";
    generation++;
    current = null;
    imports.reset();
    inventory?.hide();
    pricing?.hide();
    wms?.hide();
    workflow?.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
inventory = mountInventory({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "inventory";
    $("inventory-nav").setAttribute("aria-current", "page");
    $("products-nav").removeAttribute("aria-current");
    $("imports-nav").removeAttribute("aria-current");
    $("customers-nav").removeAttribute("aria-current");
    $("pricing-nav").removeAttribute("aria-current");
    $("wms-nav").removeAttribute("aria-current");
    $("workflow-nav").removeAttribute("aria-current");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent =
      "Operações / Inventário";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    pricing?.hide();
    wms?.hide();
    workflow?.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
pricing = mountPricing({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "pricing";
    $("pricing-nav").setAttribute("aria-current", "page");
    $("products-nav").removeAttribute("aria-current");
    $("imports-nav").removeAttribute("aria-current");
    $("customers-nav").removeAttribute("aria-current");
    $("inventory-nav").removeAttribute("aria-current");
    $("wms-nav").removeAttribute("aria-current");
    $("workflow-nav").removeAttribute("aria-current");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent =
      "Comercial / Pricing";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    workflow?.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
wms = mountWms({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "wms";
    $("wms-nav").setAttribute("aria-current", "page");
    $("products-nav").removeAttribute("aria-current");
    $("imports-nav").removeAttribute("aria-current");
    $("customers-nav").removeAttribute("aria-current");
    $("inventory-nav").removeAttribute("aria-current");
    $("pricing-nav").removeAttribute("aria-current");
    $("workflow-nav").removeAttribute("aria-current");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent =
      "Operações / Expedição";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    workflow?.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
workflow = mountWorkflow({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "workflow";
    $("workflow-nav").setAttribute("aria-current", "page");
    $("sales-nav").removeAttribute("aria-current");
    $("procurement-nav").removeAttribute("aria-current");
    $("fiscal-nav").removeAttribute("aria-current");
    $("products-nav").removeAttribute("aria-current");
    $("imports-nav").removeAttribute("aria-current");
    $("customers-nav").removeAttribute("aria-current");
    $("inventory-nav").removeAttribute("aria-current");
    $("pricing-nav").removeAttribute("aria-current");
    $("wms-nav").removeAttribute("aria-current");
    document.querySelector(".topbar > span").textContent =
      "Governança / Aprovações";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    sales?.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
sales = mountSales({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "sales";
    $("sales-nav").setAttribute("aria-current", "page");
    $("procurement-nav").removeAttribute("aria-current");
    ["products", "imports", "customers", "inventory", "pricing", "wms", "workflow", "fiscal"].forEach(
      (name) => $(`${name}-nav`)?.removeAttribute("aria-current"),
    );
    document.querySelector(".topbar > span").textContent = "Comercial / Vendas";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    procurement?.hide();
    fiscal?.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
procurement = mountProcurement({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "procurement";
    $("procurement-nav").setAttribute("aria-current", "page");
    ["products", "imports", "customers", "inventory", "pricing", "wms", "workflow", "sales", "fiscal"].forEach(
      (name) => $(`${name}-nav`)?.removeAttribute("aria-current"),
    );
    document.querySelector(".topbar > span").textContent = "Suprimentos / Compras";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    sales.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
    fiscal?.hide();
    finance?.hide();
  },
});
fiscal = mountFiscal({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "fiscal";
    $("fiscal-nav").setAttribute("aria-current", "page");
    ["products", "imports", "customers", "inventory", "pricing", "wms", "workflow", "sales", "procurement"].forEach(
      (name) => $(`${name}-nav`)?.removeAttribute("aria-current"),
    );
    document.querySelector(".topbar > span").textContent = "Fiscal / Emissão eletrônica";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    sales.hide();
    procurement.hide();
    finance?.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
finance = mountFinance({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "finance";
    $("finance-nav").setAttribute("aria-current", "page");
    [
      "products",
      "imports",
      "customers",
      "inventory",
      "pricing",
      "wms",
      "workflow",
      "sales",
      "procurement",
      "fiscal",
    ].forEach((name) => $(`${name}-nav`)?.removeAttribute("aria-current"));
    document.querySelector(".topbar > span").textContent =
      "Financeiro / Contas a pagar";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    sales.hide();
    procurement.hide();
    fiscal.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
treasury = mountTreasury({
  api,
  context: () => ({ company, permissions }),
  notice,
  openWorkflow: () => $("workflow-nav").click(),
  enter: () => {
    area = "treasury";
    $("treasury-nav").setAttribute("aria-current", "page");
    [
      "products",
      "imports",
      "customers",
      "inventory",
      "pricing",
      "wms",
      "workflow",
      "sales",
      "procurement",
      "fiscal",
      "finance",
    ].forEach((name) => $(`${name}-nav`)?.removeAttribute("aria-current"));
    document.querySelector(".topbar > span").textContent =
      "Financeiro / Tesouraria";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    sales.hide();
    procurement.hide();
    fiscal.hide();
    finance.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
conciliation = mountBankConciliation({
  api,
  context: () => ({ company, permissions }),
  notice,
  enter: () => {
    area = "conciliation";
    $("conciliation-nav").setAttribute("aria-current", "page");
    [
      "products",
      "imports",
      "customers",
      "inventory",
      "pricing",
      "wms",
      "workflow",
      "sales",
      "procurement",
      "fiscal",
      "finance",
      "treasury",
    ].forEach((name) => $(`${name}-nav`)?.removeAttribute("aria-current"));
    document.querySelector(".topbar > span").textContent =
      "Financeiro / Conciliação bancária";
    generation++;
    current = null;
    imports.reset();
    customers.hide();
    inventory.hide();
    pricing.hide();
    wms.hide();
    workflow.hide();
    sales.hide();
    procurement.hide();
    fiscal.hide();
    finance.hide();
    treasury.hide();
    $("catalog").hidden = true;
    $("detail").hidden = true;
  },
});
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}
function reset() {
  imports.reset();
  customers.reset();
  inventory.reset();
  pricing.reset();
  wms.reset();
  workflow.reset();
  sales.reset();
  procurement.reset();
  fiscal.reset();
  finance.reset();
  treasury.reset();
  conciliation.reset();
  $("imports-nav").hidden = true;
  $("customers-nav").hidden = true;
  $("inventory-nav").hidden = true;
  $("pricing-nav").hidden = true;
  $("wms-nav").hidden = true;
  $("workflow-nav").hidden = true;
  $("sales-nav").hidden = true;
  $("procurement-nav").hidden = true;
  $("fiscal-nav").hidden = true;
  $("finance-nav").hidden = true;
  $("treasury-nav").hidden = true;
  $("conciliation-nav").hidden = true;
  token = "";
  permissions.clear();
  current = null;
  company = "";
  generation++;
  $("token").value = "";
  $("company").replaceChildren(new Option("Conecte-se para selecionar", ""));
  $("company").disabled = true;
  ["catalog", "detail", "disconnect", "dev-banner"].forEach(
    (id) => ($(id).hidden = true),
  );
  $("connection").hidden = false;
  $("connection-status").textContent = "Não conectado";
  lastCreation = { body: "", key: "" };
  $("create-dialog").close();
  $("create-form").reset();
  $("detail-form").reset();
  $("barcode-form").reset();
  [
    "product-rows",
    "barcode-list",
    "lifecycle-track",
    "transition-actions",
  ].forEach((id) => $(id).replaceChildren());
  ["detail-title", "detail-code", "detail-meta", "detail-version"].forEach(
    (id) => ($(id).textContent = ""),
  );
}
async function api(
  path,
  {
    method = "GET",
    body,
    version,
    key,
    raw,
    form,
    binary = false,
    contentType,
  } = {},
) {
  const requestToken = token;
  const headers = { Authorization: `Bearer ${requestToken}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (raw !== undefined)
    headers["Content-Type"] =
      contentType ||
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  if (version !== undefined) headers["If-Match"] = `"${version}"`;
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      method,
      headers,
      body:
        form !== undefined
          ? form
          : raw !== undefined
          ? raw
          : body === undefined
            ? undefined
            : JSON.stringify(body),
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new Error(
      "Não foi possível conectar. Verifique a aplicação e tente novamente.",
    );
  }
  if (response.ok && binary) return response.blob();
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && requestToken === token) reset();
    const code = result.error?.code || "UNKNOWN";
    const trace = result.error?.correlation_id;
    const error = new Error(
      `${errors[code] || result.error?.message || "Não foi possível concluir a operação."}${trace ? ` Referência: ${trace}` : ""}`,
    );
    error.code = code;
    throw error;
  }
  return result;
}
function bind(id, action, event = "click") {
  $(id).addEventListener(event, async (e) => {
    e.preventDefault();
    try {
      if (id.endsWith("-nav") && id !== "treasury-nav") treasury?.hide();
      if (id.endsWith("-nav") && id !== "conciliation-nav") {
        conciliation?.hide();
      }
      await action(e);
    } catch (error) {
      notice(error.message);
    }
  });
}
async function connect() {
  token = $("token").value.trim();
  $("token").value = "";
  const context = await api("admin/session-context");
  permissions = new Set(context.permissions);
  const { items } = await api("admin/companies?status=ACTIVE");
  $("company").replaceChildren(
    ...items.map(
      (item) => new Option(item.trade_name || item.legal_name, item.id),
    ),
  );
  $("company").disabled = !items.length;
  company = items[0]?.id || "";
  $("connection").hidden = true;
  $("disconnect").hidden = false;
  $("dev-banner").hidden = !context.development_auth;
  $("connection-status").textContent = context.development_auth
    ? "Conectado · desenvolvimento"
    : "Conectado";
  $("new-product").hidden = !can("create");
  $("imports-nav").hidden = !permissions.has("data.import.execute");
  $("customers-nav").hidden = !permissions.has("crm.customer.read");
  $("inventory-nav").hidden =
    !permissions.has("inventory.balance.read") &&
    !permissions.has("inventory.availability.read") &&
    !permissions.has("inventory.warehouse.read") &&
    !permissions.has("inventory.adjustment.create") &&
    !permissions.has("inventory.reservation.manage");
  $("pricing-nav").hidden =
    !permissions.has("pricing.price.simulate") &&
    !permissions.has("pricing.price.create") &&
    !permissions.has("pricing.price.activate") &&
    !permissions.has("pricing.margin.view");
  $("wms-nav").hidden =
    !permissions.has("wms.pick.execute") && !permissions.has("wms.pack.execute");
  $("workflow-nav").hidden =
    !permissions.has("workflow.request.read") &&
    !permissions.has("workflow.definition.manage");
  $("sales-nav").hidden =
    !permissions.has("sales.quote.read") && !permissions.has("sales.order.read");
  $("procurement-nav").hidden =
    !permissions.has("procurement.supplier.read") &&
    !permissions.has("procurement.requisition.read") &&
    !permissions.has("procurement.order.read") &&
    !permissions.has("procurement.matching.read");
  $("fiscal-nav").hidden =
    !permissions.has("fiscal.nfe.read") &&
    !permissions.has("fiscal.inbound.read");
  $("finance-nav").hidden = !permissions.has("finance.payable.read");
  $("treasury-nav").hidden = !permissions.has("finance.treasury.read");
  $("conciliation-nav").hidden = !permissions.has(
    "finance.reconciliation.read",
  );
  if (!company) {
    notice(
      "Nenhuma empresa ativa autorizada. Configure os escopos da identidade.",
    );
    return;
  }
  notice("");
  page = 1;
  if (
    window.location.pathname
      .replace(/\/$/, "")
      .endsWith("/finance/conciliation") &&
    permissions.has("finance.reconciliation.read")
  ) {
    await conciliation.show();
    return;
  }
  if (
    window.location.pathname.replace(/\/$/, "").endsWith("/treasury") &&
    permissions.has("finance.treasury.read")
  ) {
    await treasury.show();
    return;
  }
  await loadList();
}
async function loadList() {
  area = "products";
  $("products-nav").setAttribute("aria-current", "page");
  $("imports-nav").removeAttribute("aria-current");
  $("customers-nav").removeAttribute("aria-current");
  $("inventory-nav").removeAttribute("aria-current");
  $("pricing-nav").removeAttribute("aria-current");
  $("wms-nav").removeAttribute("aria-current");
  $("workflow-nav").removeAttribute("aria-current");
  $("sales-nav").removeAttribute("aria-current");
  $("procurement-nav").removeAttribute("aria-current");
  $("fiscal-nav").removeAttribute("aria-current");
  $("finance-nav").removeAttribute("aria-current");
  $("treasury-nav").removeAttribute("aria-current");
  $("conciliation-nav").removeAttribute("aria-current");
  document.querySelector(".topbar > span").textContent = "Cadastros / Produtos";
  imports.reset();
  customers.hide();
  inventory.hide();
  pricing.hide();
  wms.hide();
  workflow.hide();
  sales.hide();
  procurement.hide();
  fiscal.hide();
  finance.hide();
  treasury.hide();
  conciliation.hide();
  const epoch = ++generation;
  current = null;
  $("detail").hidden = true;
  $("catalog").hidden = false;
  $("product-rows").replaceChildren();
  $("empty").hidden = true;
  $("page-label").textContent = "Carregando…";
  $("previous").disabled = true;
  $("next").disabled = true;
  const filter = $("lifecycle-filter").value;
  const result = await api(
    `products?company_id=${company}&page=${page}&page_size=20${filter ? `&lifecycle=${filter}` : ""}`,
  );
  if (epoch !== generation) return;
  for (const item of result.data) {
    const row = document.createElement("tr");
    const code = document.createElement("td");
    const strong = document.createElement("strong"),
      sku = document.createElement("small");
    strong.textContent = item.code;
    sku.textContent = item.sku;
    code.append(strong, sku);
    row.append(code);
    for (const value of [item.name, item.product_type, item.uom]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const state = document.createElement("td"),
      badge = document.createElement("span");
    badge.className = `status ${item.lifecycle}`;
    badge.textContent = labels[item.lifecycle];
    state.append(badge);
    row.append(state);
    const action = document.createElement("td"),
      button = document.createElement("button");
    button.className = "quiet";
    button.textContent = "Abrir →";
    button.setAttribute("aria-label", `Abrir ${item.name}`);
    button.addEventListener("click", () =>
      loadDetail(item.id).catch((error) => notice(error.message)),
    );
    action.append(button);
    row.append(action);
    $("product-rows").append(row);
  }
  $("empty").hidden = result.data.length > 0;
  $("page-label").textContent = `Página ${result.meta.page}`;
  $("previous").disabled = page === 1;
  $("next").disabled = !result.meta.has_more;
}
async function loadDetail(id) {
  const epoch = ++generation;
  const item = await api(`products/${id}?company_id=${company}`);
  const barcodes = await api(`products/${id}/barcodes?company_id=${company}`);
  if (epoch !== generation) return;
  current = item;
  $("catalog").hidden = true;
  $("detail").hidden = false;
  $("detail-code").textContent = `${item.code} / ${item.sku}`;
  $("detail-title").textContent = item.name;
  $("detail-meta").textContent = `${item.product_type} · ${item.uom}`;
  $("detail-version").textContent = `Versão ${item.version}`;
  $("detail-name").value = item.name;
  $("detail-uom").value = item.uom;
  ["detail-name", "detail-uom", "save-details"].forEach(
    (id) => ($(id).disabled = !can("update")),
  );
  $("barcode-form").hidden = !can("update");
  $("lifecycle-track").replaceChildren(
    ...Object.entries(labels).map(([state, label]) => {
      const li = document.createElement("li");
      li.textContent = label;
      if (state === item.lifecycle) {
        li.className = "current";
        li.setAttribute("aria-current", "step");
      }
      return li;
    }),
  );
  $("barcode-list").replaceChildren(
    ...barcodes.data.map((code) => {
      const li = document.createElement("li"),
        small = document.createElement("small");
      small.textContent = code.barcode_type;
      li.append(small, document.createTextNode(code.barcode));
      return li;
    }),
  );
  if (!barcodes.data.length) {
    const li = document.createElement("li");
    li.textContent = "Nenhum código cadastrado.";
    $("barcode-list").append(li);
  }
  $("transition-actions").replaceChildren();
  const transition = {
    EM_DESENVOLVIMENTO: [
      "submit-for-homologation",
      "Enviar para homologação",
      "activate",
    ],
    EM_HOMOLOGACAO: ["activate", "Ativar produto", "activate"],
    ATIVO: ["discontinue", "Descontinuar produto", "discontinue"],
  }[item.lifecycle];
  if (transition && can(transition[2])) {
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = transition[1];
    button.addEventListener("click", async () => {
      if (
        !confirm(
          `${transition[1]}? Esta transição não possui reversão automática.`,
        )
      )
        return;
      button.disabled = true;
      try {
        await api(
          `products/${item.id}/${transition[0]}?company_id=${company}`,
          { method: "POST", version: item.version, key: crypto.randomUUID() },
        );
        await loadDetail(item.id);
        notice("Situação atualizada.");
      } catch (error) {
        notice(error.message);
        button.disabled = false;
      }
    });
    $("transition-actions").append(button);
  }
}
bind(
  "connect-form",
  async (event) => {
    event.submitter.disabled = true;
    try {
      await connect();
    } finally {
      event.submitter.disabled = false;
    }
  },
  "submit",
);
bind("disconnect", () => {
  reset();
  notice("Conexão encerrada.");
});
bind(
  "company",
  async () => {
    company = $("company").value;
    page = 1;
    notice("");
    $("create-dialog").close();
    if (area === "customers") return customers.show();
    if (area === "inventory") return inventory.show();
    if (area === "pricing") return pricing.show();
    if (area === "wms") return wms.show();
    if (area === "workflow") return workflow.show();
    if (area === "sales") return sales.show();
    if (area === "procurement") return procurement.show();
    if (area === "fiscal") return fiscal.show();
    if (area === "finance") return finance.show();
    if (area === "treasury") return treasury.show();
    await loadList();
  },
  "change",
);
bind(
  "lifecycle-filter",
  async () => {
    page = 1;
    await loadList();
  },
  "change",
);
bind("refresh", () => loadList());
bind("imports-nav", () => imports.show());
bind("customers-nav", () => {
  if (company) return customers.show();
});
bind("inventory-nav", () => {
  if (company) return inventory.show();
});
bind("pricing-nav", () => {
  if (company) return pricing.show();
});
bind("wms-nav", () => {
  if (company) return wms.show();
});
bind("workflow-nav", () => {
  if (company) return workflow.show();
});
bind("sales-nav", () => {
  if (company) return sales.show();
});
bind("procurement-nav", () => {
  if (company) return procurement.show();
});
bind("fiscal-nav", () => {
  if (company) return fiscal.show();
});
bind("finance-nav", () => {
  if (company) return finance.show();
});
bind("treasury-nav", () => {
  if (company) return treasury.show();
});
bind("conciliation-nav", () => {
  if (company) return conciliation.show();
});
bind("products-nav", () => {
  if (company) return loadList();
});
bind("refresh-detail", () => {
  notice("");
  if (current) return loadDetail(current.id);
});
bind("back", () => {
  notice("");
  return loadList();
});
bind("previous", () => {
  page--;
  return loadList();
});
bind("next", () => {
  page++;
  return loadList();
});
bind("new-product", () => {
  $("create-error").hidden = true;
  $("create-dialog").showModal();
  $("create-code").focus();
});
bind("close-create", () => $("create-dialog").close());
$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("create-error").hidden = true;
  const body = {
    company_id: company,
    ...Object.fromEntries(new FormData(event.target)),
  };
  const fingerprint = JSON.stringify(body);
  if (lastCreation.body !== fingerprint)
    lastCreation = { body: fingerprint, key: crypto.randomUUID() };
  try {
    const result = await api("products", {
      method: "POST",
      body,
      key: lastCreation.key,
    });
    $("create-dialog").close();
    event.target.reset();
    lastCreation = { body: "", key: "" };
    await loadDetail(result.product.id);
    notice("Produto criado em desenvolvimento.");
  } catch (error) {
    $("create-error").textContent = error.message;
    $("create-error").hidden = false;
  } finally {
    button.disabled = false;
  }
});
bind(
  "detail-form",
  async (event) => {
    const item = current,
      button = event.submitter;
    button.disabled = true;
    try {
      await api(`products/${item.id}?company_id=${company}`, {
        method: "PATCH",
        version: item.version,
        body: { name: $("detail-name").value, uom: $("detail-uom").value },
      });
      await loadDetail(item.id);
      notice("Alterações salvas.");
    } finally {
      button.disabled = !can("update");
    }
  },
  "submit",
);
bind(
  "barcode-form",
  async (event) => {
    const item = current,
      button = event.submitter;
    button.disabled = true;
    try {
      await api(`products/${item.id}/barcodes?company_id=${company}`, {
        method: "POST",
        version: item.version,
        key: crypto.randomUUID(),
        body: {
          barcode_type: $("barcode-type").value,
          barcode: $("barcode-value").value,
        },
      });
      $("barcode-value").value = "";
      await loadDetail(item.id);
      notice("Código de barras adicionado.");
    } finally {
      button.disabled = false;
    }
  },
  "submit",
);
