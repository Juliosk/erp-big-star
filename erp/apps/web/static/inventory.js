const $ = (id) => document.getElementById(id);

const can = (permissions, permission) => permissions.has(permission);

function text(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function clear(...ids) {
  ids.forEach((id) => $(id).replaceChildren());
}

function option(label, value) {
  const item = new Option(label, value);
  item.title = value;
  return item;
}

function row(...values) {
  const tr = document.createElement("tr");
  values.forEach((value) => {
    const td = document.createElement("td");
    if (value instanceof Node) td.append(value);
    else td.textContent = text(value);
    tr.append(td);
  });
  return tr;
}

function compactId(id) {
  return `${String(id).slice(0, 8)}…`;
}

export function mountInventory({ api, context, notice, enter }) {
  let page = 1;
  let lots = [];
  let warehouses = [];

  const query = () => `company_id=${context().company}`;

  function hide() {
    $("inventory").hidden = true;
  }

  function reset() {
    hide();
    page = 1;
    lots = [];
    warehouses = [];
    clear(
      "inventory-balance-rows",
      "inventory-warehouse-rows",
      "inventory-lot-rows",
      "inventory-trace-rows",
    );
    $("inventory-empty").hidden = true;
    $("inventory-page-label").textContent = "Página 1";
    $("inventory-adjustment-form").reset();
    $("inventory-lot-filter").replaceChildren(option("Todos os lotes", ""));
    $("inventory-warehouse-id").replaceChildren(option("Cadastre um depósito", ""));
    $("inventory-lot-id").replaceChildren(option("Sem lote", ""));
    $("inventory-trace-lot-id").replaceChildren(option("Selecione um lote", ""));
  }

  function renderSelectors() {
    $("inventory-warehouse-id").replaceChildren(
      ...(
        warehouses.length
          ? warehouses.map((item) => option(`${item.code} · ${item.name}`, item.id))
          : [option("Cadastre um depósito", "")]
      ),
    );
    const lotOptions = () =>
      lots.map((item) => option(`${item.code} · ${compactId(item.product_id)}`, item.id));
    $("inventory-lot-filter").replaceChildren(option("Todos os lotes", ""), ...lotOptions());
    $("inventory-lot-id").replaceChildren(option("Sem lote", ""), ...lotOptions());
    $("inventory-trace-lot-id").replaceChildren(
      ...(lots.length ? lotOptions() : [option("Selecione um lote", "")]),
    );
  }

  async function loadStructure() {
    const [warehouseResult, lotResult] = await Promise.all([
      api(`inventory/warehouses?${query()}&page_size=100`),
      api(`inventory/lots?${query()}&page_size=100`),
    ]);
    warehouses = warehouseResult.data;
    lots = lotResult.data;
    $("inventory-warehouse-rows").replaceChildren(
      ...warehouses.map((item) =>
        row(
          item.code,
          item.name,
          item.active ? "Ativo" : "Inativo",
          `Versão ${item.version}`,
        ),
      ),
    );
    $("inventory-lot-rows").replaceChildren(
      ...lots.map((item) =>
        row(
          item.code,
          compactId(item.product_id),
          item.status,
          item.expires_on || "Sem vencimento",
        ),
      ),
    );
    renderSelectors();
  }

  async function loadBalances() {
    $("inventory").setAttribute("aria-busy", "true");
    $("inventory-balance-rows").replaceChildren();
    $("inventory-empty").hidden = true;
    $("inventory-page-label").textContent = "Carregando…";
    const lot = $("inventory-lot-filter").value;
    try {
      const result = await api(
        `inventory/balances?${query()}&page=${page}&page_size=20${lot ? `&lot_id=${lot}` : ""}`,
      );
      $("inventory-balance-rows").replaceChildren(
        ...result.data.map((item) =>
          row(
            compactId(item.product_id),
            compactId(item.warehouse_id),
            item.lot_id ? compactId(item.lot_id) : "Sem lote",
            item.state,
            item.quantity,
            `v${item.version}`,
          ),
        ),
      );
      $("inventory-empty").hidden = result.data.length > 0;
      $("inventory-page-label").textContent = `Página ${result.meta.page}`;
      $("inventory-previous").disabled = page === 1;
      $("inventory-next").disabled = !result.meta.has_more;
    } finally {
      $("inventory").removeAttribute("aria-busy");
    }
  }

  async function loadTrace() {
    const lot = $("inventory-trace-lot-id").value;
    $("inventory-trace-rows").replaceChildren();
    if (!lot) return;
    const result = await api(`inventory/lots/${lot}/postings?${query()}&page_size=50`);
    $("inventory-trace-rows").replaceChildren(
      ...result.data.map((item) =>
        row(
          compactId(item.transaction_id),
          item.sequence,
          item.state,
          item.quantity_delta,
          compactId(item.warehouse_id),
        ),
      ),
    );
  }

  async function loadAll() {
    await loadStructure();
    await loadBalances();
    await loadTrace();
  }

  async function show() {
    enter();
    $("inventory").hidden = false;
    const { permissions } = context();
    $("inventory-adjustment-form").hidden = !can(
      permissions,
      "inventory.adjustment.create",
    );
    $("inventory-readonly").hidden = can(permissions, "inventory.adjustment.create");
    await loadAll();
  }

  $("inventory-refresh").addEventListener("click", () =>
    loadAll().catch((error) => notice(error.message)),
  );
  $("inventory-lot-filter").addEventListener("change", () => {
    page = 1;
    loadBalances().catch((error) => notice(error.message));
  });
  $("inventory-previous").addEventListener("click", () => {
    page--;
    loadBalances().catch((error) => notice(error.message));
  });
  $("inventory-next").addEventListener("click", () => {
    page++;
    loadBalances().catch((error) => notice(error.message));
  });
  $("inventory-trace-refresh").addEventListener("click", () =>
    loadTrace().catch((error) => notice(error.message)),
  );
  $("inventory-trace-lot-id").addEventListener("change", () =>
    loadTrace().catch((error) => notice(error.message)),
  );
  $("inventory-adjustment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const body = {
        company_id: context().company,
        adjustment_type: $("inventory-adjustment-type").value,
        reason: $("inventory-adjustment-reason").value,
        lines: [
          {
            product_id: $("inventory-product-id").value.trim(),
            warehouse_id: $("inventory-warehouse-id").value,
            lot_id: $("inventory-lot-id").value || null,
            state: $("inventory-state").value,
            quantity: $("inventory-adjustment-quantity").value,
          },
        ],
      };
      await api("inventory/adjustments", {
        method: "POST",
        body,
        key: crypto.randomUUID(),
      });
      $("inventory-adjustment-quantity").value = "";
      await loadAll();
      notice("Ajuste registrado no ledger e saldo atualizado.");
    } finally {
      button.disabled = false;
    }
  });

  return { hide, reset, show };
}
