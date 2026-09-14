const $ = (id) => document.getElementById(id);

const currency = new Intl.NumberFormat("pt-BR", {
  currency: "BRL",
  style: "currency",
});
const number = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 4,
  minimumFractionDigits: 2,
});

const can = (permissions, permission) => permissions.has(permission);
const compact = (value) => (value ? `${value}`.slice(0, 8) : "—");
const amount = (value) => (value === null || value === undefined ? "—" : currency.format(Number(value)));
const margin = (value) =>
  value === null || value === undefined ? "—" : `${number.format(Number(value) * 100)}%`;

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value;
  return td;
}

function badge(value) {
  const span = document.createElement("span");
  span.className = `status ${value}`;
  span.textContent = value;
  return span;
}

function readDecimal(id) {
  const value = $(id).value.trim();
  return value === "" ? null : value;
}

function setDisabled(form, disabled) {
  for (const element of form.querySelectorAll("input, select, textarea, button")) {
    element.disabled = disabled;
  }
}

export function mountPricing({ api, context, notice, enter }) {
  let selectedList = null;
  let versions = [];

  const query = () => `company_id=${context().company}`;

  function hide() {
    $("pricing").hidden = true;
  }

  function reset() {
    hide();
    selectedList = null;
    versions = [];
    $("pricing-list-form").reset();
    $("pricing-version-form").reset();
    $("pricing-simulation-form").reset();
    $("pricing-simulation-quantity").value = "1";
    $("pricing-selected-title").textContent = "Nenhuma lista selecionada";
    $("pricing-selected-meta").textContent =
      "Selecione uma lista para criar e ativar versões.";
    $("pricing-decision").hidden = true;
    [
      "pricing-list-rows",
      "pricing-version-rows",
      "pricing-snapshot-rows",
    ].forEach((id) => $(id).replaceChildren());
    [
      "pricing-empty",
      "pricing-version-empty",
      "pricing-snapshots-empty",
    ].forEach((id) => ($(id).hidden = true));
  }

  async function show() {
    enter();
    $("pricing").hidden = false;
    const { permissions } = context();
    $("pricing-list-form").hidden = !can(permissions, "pricing.price.create");
    $("pricing-version-form").hidden = !can(permissions, "pricing.price.create");
    await Promise.all([loadLists(), loadSnapshots()]);
  }

  async function loadLists() {
    const result = await api(`pricing/price-lists?${query()}&page=1&page_size=50`);
    $("pricing-list-rows").replaceChildren();
    for (const item of result.data) {
      const row = document.createElement("tr");
      row.append(cell(item.code), cell(item.price_type));
      const statusCell = document.createElement("td");
      statusCell.append(badge(item.status));
      row.append(statusCell);
      const action = document.createElement("td");
      const button = document.createElement("button");
      button.className = "quiet";
      button.type = "button";
      button.textContent = "Selecionar";
      button.addEventListener("click", () => {
        selectedList = item;
        renderSelected();
        loadVersions().catch((error) => notice(error.message));
      });
      action.append(button);
      row.append(action);
      $("pricing-list-rows").append(row);
    }
    $("pricing-empty").hidden = result.data.length > 0;
    if (
      selectedList &&
      !result.data.some((item) => item.id === selectedList.id)
    ) {
      selectedList = null;
      versions = [];
    }
    if (!selectedList && result.data.length) selectedList = result.data[0];
    renderSelected();
    await loadVersions();
  }

  function renderSelected() {
    if (!selectedList) {
      $("pricing-selected-title").textContent = "Nenhuma lista selecionada";
      $("pricing-selected-meta").textContent =
        "Selecione uma lista para criar e ativar versões.";
      return;
    }
    $("pricing-selected-title").textContent = selectedList.name;
    $("pricing-selected-meta").textContent =
      `${selectedList.code} · ${selectedList.price_type} · versão ${selectedList.version}`;
    $("pricing-simulation-list-id").placeholder = `Selecionada: ${selectedList.id}`;
  }

  async function loadVersions() {
    $("pricing-version-rows").replaceChildren();
    if (!selectedList) {
      $("pricing-version-empty").hidden = false;
      return;
    }
    const result = await api(
      `pricing/price-lists/${selectedList.id}/versions?${query()}&page=1&page_size=50`,
    );
    versions = result.data;
    const { permissions } = context();
    for (const item of versions) {
      const row = document.createElement("tr");
      row.append(cell(item.sequence));
      const statusCell = document.createElement("td");
      statusCell.append(badge(item.status));
      row.append(statusCell);
      row.append(
        cell(item.valid_from),
        cell(`${item.items.length} item(ns)`),
      );
      const action = document.createElement("td");
      const button = document.createElement("button");
      button.className = "quiet";
      button.type = "button";
      button.textContent = "Ativar";
      button.disabled =
        item.status !== "DRAFT" || !can(permissions, "pricing.price.activate");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(
            `pricing/price-list-versions/${item.id}/activate?${query()}`,
            {
              key: crypto.randomUUID(),
              method: "POST",
              version: item.version,
            },
          );
          notice("Versão de lista ativada.");
          await Promise.all([loadLists(), loadSnapshots()]);
        } catch (error) {
          notice(error.message);
          button.disabled = false;
        }
      });
      action.append(button);
      row.append(action);
      $("pricing-version-rows").append(row);
    }
    $("pricing-version-empty").hidden = versions.length > 0;
  }

  async function loadSnapshots() {
    const filter = $("pricing-snapshot-product-filter").value.trim();
    const result = await api(
      `pricing/snapshots?${query()}&page=1&page_size=20${filter ? `&product_id=${filter}` : ""}`,
    );
    $("pricing-snapshot-rows").replaceChildren();
    for (const item of result.data) {
      const row = document.createElement("tr");
      row.append(
        cell(compact(item.id)),
        cell(compact(item.product_id)),
        cell(compact(item.price_list_id)),
        cell(`${item.cost_source} · ${amount(item.cost_amount)}`),
        cell(amount(item.rounded_price)),
        cell(margin(item.minimum_margin)),
        cell(item.source),
        cell(new Date(item.created_at).toLocaleString("pt-BR")),
      );
      $("pricing-snapshot-rows").append(row);
    }
    $("pricing-snapshots-empty").hidden = result.data.length > 0;
  }

  function pricingPayload() {
    const priceListId = $("pricing-simulation-list-id").value.trim();
    return {
      company_id: context().company,
      product_id: $("pricing-simulation-product-id").value.trim(),
      quantity: $("pricing-simulation-quantity").value,
      price_list_id: priceListId || selectedList?.id || null,
    };
  }

  function renderDecision(result) {
    $("pricing-decision").hidden = false;
    $("pricing-decision").replaceChildren();
    const items = [
      ["Preço unitário", amount(result.unit_price)],
      ["Total", amount(result.total_price)],
      ["Margem calculada", margin(result.margin)],
      ["Margem mínima", margin(result.minimum_margin)],
      ["Custo", amount(result.cost_amount)],
      ["Snapshot", result.persisted ? compact(result.pricing_snapshot_id) : "não persistido"],
      ["Fonte", result.source],
    ];
    for (const [label, value] of items) {
      const card = document.createElement("article");
      const small = document.createElement("small");
      const strong = document.createElement("strong");
      small.textContent = label;
      strong.textContent = value;
      card.append(small, strong);
      $("pricing-decision").append(card);
    }
  }

  $("pricing-refresh").addEventListener("click", async () => {
    try {
      await Promise.all([loadLists(), loadSnapshots()]);
      notice("");
    } catch (error) {
      notice(error.message);
    }
  });

  $("pricing-snapshot-refresh").addEventListener("click", async () => {
    try {
      await loadSnapshots();
      notice("");
    } catch (error) {
      notice(error.message);
    }
  });

  $("pricing-list-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const body = {
        code: $("pricing-code").value.trim(),
        company_id: context().company,
        currency: "BRL",
        name: $("pricing-name").value.trim(),
        price_type: $("pricing-type").value,
      };
      selectedList = await api("pricing/price-lists", {
        body,
        key: crypto.randomUUID(),
        method: "POST",
      });
      $("pricing-list-form").reset();
      await loadLists();
      notice("Lista de preço criada.");
    } finally {
      button.disabled = false;
    }
  });

  $("pricing-version-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedList) {
      notice("Selecione uma lista antes de criar a versão.");
      return;
    }
    const button = event.submitter;
    button.disabled = true;
    try {
      const body = {
        company_id: context().company,
        items: [
          {
            minimum_price_amount: readDecimal("pricing-minimum-price"),
            price_amount: $("pricing-price-amount").value,
            product_id: $("pricing-version-product-id").value.trim(),
            target_margin: readDecimal("pricing-target-margin"),
          },
        ],
        source: $("pricing-version-source").value.trim() || "COCKPIT",
        valid_from: $("pricing-valid-from").value,
      };
      await api(`pricing/price-lists/${selectedList.id}/versions`, {
        body,
        key: crypto.randomUUID(),
        method: "POST",
      });
      $("pricing-version-form").reset();
      $("pricing-version-source").value = "COCKPIT";
      await loadVersions();
      notice("Versão de lista criada em rascunho.");
    } finally {
      button.disabled = false;
    }
  });

  $("pricing-simulation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    const form = event.currentTarget;
    setDisabled(form, true);
    try {
      const body = pricingPayload();
      let result;
      if (button.id === "pricing-resolve-run") {
        result = await api("pricing/resolve", { body, method: "POST" });
        await loadSnapshots();
      } else {
        body.proposed_unit_price = readDecimal("pricing-proposed-price");
        result = await api("pricing/simulate", { body, method: "POST" });
      }
      renderDecision(result);
      notice(
        result.persisted
          ? "Preço resolvido e snapshot persistido."
          : "Simulação calculada sem persistir snapshot.",
      );
    } finally {
      setDisabled(form, false);
    }
  });

  return { hide, reset, show };
}
