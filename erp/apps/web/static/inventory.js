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
  let reservationPage = 1;
  let lots = [];
  let pools = [];
  let warehouses = [];

  const query = () => `company_id=${context().company}`;

  function hide() {
    $("inventory").hidden = true;
  }

  function reset() {
    hide();
    page = 1;
    reservationPage = 1;
    lots = [];
    pools = [];
    warehouses = [];
    clear(
      "inventory-balance-rows",
      "inventory-availability-rows",
      "inventory-reservation-rows",
      "inventory-warehouse-rows",
      "inventory-lot-rows",
      "inventory-trace-rows",
    );
    $("inventory-empty").hidden = true;
    $("inventory-availability-empty").hidden = true;
    $("inventory-page-label").textContent = "Página 1";
    $("inventory-adjustment-form").reset();
    $("inventory-reservation-form").reset();
    $("inventory-lot-filter").replaceChildren(option("Todos os lotes", ""));
    $("inventory-warehouse-id").replaceChildren(option("Cadastre um depósito", ""));
    $("inventory-reservation-warehouse-id").replaceChildren(
      option("Cadastre um depósito", ""),
    );
    $("inventory-lot-id").replaceChildren(option("Sem lote", ""));
    $("inventory-reservation-lot-id").replaceChildren(option("Sem lote", ""));
    $("inventory-reservation-pool-id").replaceChildren(option("Sem pool", ""));
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
    $("inventory-reservation-warehouse-id").replaceChildren(
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
    $("inventory-reservation-lot-id").replaceChildren(
      option("Sem lote", ""),
      ...lotOptions(),
    );
    $("inventory-reservation-pool-id").replaceChildren(
      option("Sem pool", ""),
      ...pools.map((item) => option(`${item.code} · ${item.name}`, item.id)),
    );
    $("inventory-trace-lot-id").replaceChildren(
      ...(lots.length ? lotOptions() : [option("Selecione um lote", "")]),
    );
  }

  async function loadStructure() {
    const [warehouseResult, lotResult, poolResult] = await Promise.all([
      api(`inventory/warehouses?${query()}&page_size=100`),
      api(`inventory/lots?${query()}&page_size=100`),
      api(`inventory/pools?${query()}&page_size=100`),
    ]);
    warehouses = warehouseResult.data;
    lots = lotResult.data;
    pools = poolResult.data;
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

  async function loadAvailability() {
    const lot = $("inventory-lot-filter").value;
    $("inventory-availability-rows").replaceChildren();
    const result = await api(
      `inventory/availability?${query()}&page_size=20${lot ? `&lot_id=${lot}` : ""}`,
    );
    $("inventory-availability-rows").replaceChildren(
      ...result.data.map((item) =>
        row(
          compactId(item.product_id),
          compactId(item.warehouse_id),
          `${item.lot_id ? compactId(item.lot_id) : "Sem lote"} / ${
            item.pool_id ? compactId(item.pool_id) : "Sem pool"
          }`,
          item.state,
          item.on_hand,
          item.hard_reserved,
          item.soft_reserved,
          item.available,
        ),
      ),
    );
    $("inventory-availability-empty").hidden = result.data.length > 0;
  }

  function reservationAction(item) {
    const button = document.createElement("button");
    button.className = "quiet";
    button.textContent = item.status === "ACTIVE" ? "Liberar" : "—";
    button.disabled = item.status !== "ACTIVE";
    if (item.status === "ACTIVE") {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`inventory/reservations/${item.id}/release?${query()}`, {
            method: "POST",
            version: item.version,
            key: crypto.randomUUID(),
          });
          await loadAll();
          notice("Reserva liberada e ATP recalculado.");
        } catch (error) {
          notice(error.message);
          button.disabled = false;
        }
      });
    }
    return button;
  }

  function reservationBucket(item) {
    const allocation = item.allocations[0];
    if (!allocation) return "Sem allocation";
    return `${compactId(allocation.product_id)} · ${compactId(allocation.warehouse_id)} · ${
      allocation.lot_id ? compactId(allocation.lot_id) : "sem lote"
    }`;
  }

  function reservationQuantity(item) {
    return item.allocations
      .reduce((total, allocation) => total + Number(allocation.quantity), 0)
      .toFixed(6);
  }

  async function loadReservations() {
    $("inventory-reservation-rows").replaceChildren();
    const result = await api(
      `inventory/reservations?${query()}&page=${reservationPage}&page_size=20`,
    );
    $("inventory-reservation-rows").replaceChildren(
      ...result.data.map((item) =>
        row(
          `${item.reference_type} · ${compactId(item.reference_id)}`,
          item.reservation_kind,
          item.status,
          reservationBucket(item),
          reservationQuantity(item),
          `v${item.version}`,
          reservationAction(item),
        ),
      ),
    );
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
    await loadAvailability();
    await loadReservations();
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
    $("inventory-reservation-form").hidden = !can(
      permissions,
      "inventory.reservation.manage",
    );
    $("inventory-reservation-readonly").hidden = can(
      permissions,
      "inventory.reservation.manage",
    );
    await loadAll();
  }

  $("inventory-refresh").addEventListener("click", () =>
    loadAll().catch((error) => notice(error.message)),
  );
  $("inventory-lot-filter").addEventListener("change", () => {
    page = 1;
    Promise.all([loadBalances(), loadAvailability()]).catch((error) =>
      notice(error.message),
    );
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
  $("inventory-availability-refresh").addEventListener("click", () =>
    Promise.all([loadAvailability(), loadReservations()]).catch((error) =>
      notice(error.message),
    ),
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
  $("inventory-reservation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const expiresAt = $("inventory-reservation-expires-at").value;
      const body = {
        company_id: context().company,
        reservation_kind: $("inventory-reservation-kind").value,
        reference_type: "UI",
        reference_id:
          $("inventory-reservation-reference-id").value.trim() ||
          crypto.randomUUID(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        lines: [
          {
            product_id: $("inventory-reservation-product-id").value.trim(),
            warehouse_id: $("inventory-reservation-warehouse-id").value,
            lot_id: $("inventory-reservation-lot-id").value || null,
            pool_id: $("inventory-reservation-pool-id").value || null,
            state: $("inventory-reservation-state").value,
            quantity: $("inventory-reservation-quantity").value,
          },
        ],
      };
      await api("inventory/reservations", {
        method: "POST",
        body,
        key: crypto.randomUUID(),
      });
      $("inventory-reservation-quantity").value = "";
      $("inventory-reservation-reference-id").value = "";
      await loadAll();
      notice("Reserva criada e disponibilidade ATP atualizada.");
    } finally {
      button.disabled = false;
    }
  });

  return { hide, reset, show };
}
