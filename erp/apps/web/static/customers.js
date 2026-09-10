const $ = (id) => document.getElementById(id);

const statuses = {
  ACTIVE: "Ativo",
  INACTIVE: "Inativo",
  BLOCKED: "Bloqueado",
};

const customerTypes = {
  INDIVIDUAL: "Pessoa física",
  COMPANY: "Pessoa jurídica",
};

const identityLabels = {
  CPF: "CPF",
  CNPJ: "CNPJ",
};

const can = (permissions, action) => permissions.has(`crm.customer.${action}`);

function emptyList(target, message) {
  const item = document.createElement("li");
  item.textContent = message;
  target.append(item);
}

function badge(value) {
  const span = document.createElement("span");
  span.className = `status ${value}`;
  span.textContent = statuses[value] || value;
  return span;
}

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value;
  return td;
}

export function mountCustomers({ api, context, notice, enter }) {
  let page = 1,
    current = null,
    lastCreation = { body: "", key: "" };

  function hide() {
    ["customers", "customer-detail", "customer-groups"].forEach((id) => ($(id).hidden = true));
    $("customer-create-dialog").close();
    $("group-create-dialog").close();
  }

  function reset() {
    page = 1;
    current = null;
    lastCreation = { body: "", key: "" };
    hide();
    [
      "customer-rows",
      "customer-contact-list",
      "customer-address-list",
      "customer-group-list",
      "customer-merge-list",
      "customer-group-rows",
    ].forEach((id) => $(id).replaceChildren());
    ["customer-detail-title", "customer-detail-identity", "customer-detail-meta"].forEach(
      (id) => ($(id).textContent = ""),
    );
    $("customer-create-form").reset();
    $("customer-edit-form").reset();
    $("group-create-form").reset();
  }

  async function show() {
    enter();
    page = 1;
    await loadList();
  }

  async function loadList() {
    enter();
    const { company, permissions } = context();
    current = null;
    $("customers").hidden = false;
    $("customer-detail").hidden = true;
    $("customer-groups").hidden = true;
    $("new-customer").hidden = !can(permissions, "create");
    $("customer-rows").replaceChildren();
    $("customers-empty").hidden = true;
    $("customer-page-label").textContent = "Carregando…";
    $("customer-previous").disabled = true;
    $("customer-next").disabled = true;
    const status = $("customer-status-filter").value;
    const result = await api(
      `customers?company_id=${company}&page=${page}&page_size=20${status ? `&status=${status}` : ""}`,
    );
    for (const item of result.data) {
      const row = document.createElement("tr");
      const identity = document.createElement("td");
      const strong = document.createElement("strong");
      const small = document.createElement("small");
      strong.textContent = item.legal_name;
      small.textContent = `${identityLabels[item.identity_type]} · ${item.identity_ref}`;
      identity.append(strong, small);
      row.append(identity);
      row.append(cell(item.trade_name || "—"));
      row.append(cell(customerTypes[item.customer_type] || item.customer_type));
      const statusCell = document.createElement("td");
      statusCell.append(badge(item.status));
      row.append(statusCell);
      const action = document.createElement("td");
      const button = document.createElement("button");
      button.className = "quiet";
      button.textContent = "Abrir 360 →";
      button.setAttribute("aria-label", `Abrir 360 de ${item.legal_name}`);
      button.addEventListener("click", () =>
        loadDetail(item.id).catch((error) => notice(error.message)),
      );
      action.append(button);
      row.append(action);
      $("customer-rows").append(row);
    }
    $("customers-empty").hidden = result.data.length > 0;
    $("customer-page-label").textContent = `Página ${result.meta.page}`;
    $("customer-previous").disabled = page === 1;
    $("customer-next").disabled = !result.meta.has_more;
  }

  async function loadDetail(id) {
    enter();
    const { company, permissions } = context();
    const snapshot = await api(`customers/${id}/360?company_id=${company}`);
    current = snapshot.customer;
    $("customers").hidden = true;
    $("customer-groups").hidden = true;
    $("customer-detail").hidden = false;
    $("customer-detail-title").textContent = current.legal_name;
    $("customer-detail-identity").textContent =
      `${identityLabels[current.identity_type]} · ${current.identity_ref}`;
    $("customer-detail-meta").textContent =
      `${customerTypes[current.customer_type]} · Versão ${current.version}`;
    $("customer-detail-status").replaceChildren(badge(current.status));
    $("customer-legal-name").value = current.legal_name;
    $("customer-trade-name").value = current.trade_name || "";
    $("customer-status").value = current.status;
    ["customer-legal-name", "customer-trade-name", "customer-status", "save-customer"].forEach(
      (field) => ($(field).disabled = !can(permissions, "update")),
    );
    renderChildren(snapshot);
    await loadAssignableGroups(snapshot.groups);
  }

  function renderChildren(snapshot) {
    $("customer-contact-list").replaceChildren();
    for (const contact of snapshot.contacts) {
      const item = document.createElement("li");
      item.textContent =
        `${contact.role} · ${contact.kind} · ${contact.value}${contact.name ? ` (${contact.name})` : ""}`;
      $("customer-contact-list").append(item);
    }
    if (!snapshot.contacts.length) emptyList($("customer-contact-list"), "Nenhum contato.");
    $("customer-address-list").replaceChildren();
    for (const address of snapshot.addresses) {
      const item = document.createElement("li");
      item.textContent =
        `${address.role} · ${address.line1}, ${address.district || "s/bairro"} · ${address.city}/${address.state}`;
      $("customer-address-list").append(item);
    }
    if (!snapshot.addresses.length) emptyList($("customer-address-list"), "Nenhum endereço.");
    $("customer-group-list").replaceChildren();
    for (const group of snapshot.groups) {
      const item = document.createElement("li");
      item.textContent = `${group.code} · ${group.name}${group.active ? "" : " (inativo)"}`;
      $("customer-group-list").append(item);
    }
    if (!snapshot.groups.length) emptyList($("customer-group-list"), "Nenhum grupo vinculado.");
    renderMergeStatus(snapshot.merge_status);
  }

  function renderMergeStatus(mergeStatus) {
    const { permissions } = context();
    $("customer-merge-list").replaceChildren();
    for (const merge of mergeStatus.pending_merge_requests) {
      const item = document.createElement("li");
      item.textContent = `Solicitação ${merge.status} · sobrevivente ${merge.surviving_customer_id}`;
      $("customer-merge-list").append(item);
    }
    for (const duplicate of mergeStatus.duplicate_candidates) {
      const item = document.createElement("li");
      item.textContent =
        `${duplicate.status} · confiança ${duplicate.confidence}% · ${duplicate.reason_codes.join(", ")}`;
      $("customer-merge-list").append(item);
    }
    if (
      !mergeStatus.pending_merge_requests.length &&
      !mergeStatus.duplicate_candidates.length
    ) {
      emptyList($("customer-merge-list"), "Sem pendências de mesclagem.");
    }
    const candidate = mergeStatus.duplicate_candidates.find(
      (item) =>
        item.status === "SUGGESTED" &&
        (item.source_customer_id === current.id || item.candidate_customer_id === current.id),
    );
    $("request-merge").hidden = !candidate || !can(permissions, "merge");
    $("request-merge").dataset.candidateId = candidate
      ? candidate.source_customer_id === current.id
        ? candidate.candidate_customer_id
        : candidate.source_customer_id
      : "";
  }

  async function loadAssignableGroups(selectedGroups) {
    const { company, permissions } = context();
    $("customer-assign-form").hidden = !can(permissions, "update");
    if (!can(permissions, "update")) return;
    $("customer-assign-form").dataset.selectedGroupId = "";
    const selected = new Set(selectedGroups.map((group) => group.id));
    const result = await api(`customer-groups?company_id=${company}&active=true&page_size=100`);
    $("customer-assign-group").replaceChildren(
      new Option("Selecione um grupo", ""),
      ...result.data
        .filter((group) => !selected.has(group.id))
        .map((group) => new Option(`${group.code} · ${group.name}`, group.id)),
    );
    $("assign-customer-group").disabled = $("customer-assign-group").options.length <= 1;
  }

  async function showGroups() {
    enter();
    const { company, permissions } = context();
    $("customers").hidden = true;
    $("customer-detail").hidden = true;
    $("customer-groups").hidden = false;
    $("new-group").hidden = !can(permissions, "update");
    const result = await api(`customer-groups?company_id=${company}&page_size=100`);
    $("customer-group-rows").replaceChildren();
    for (const group of result.data) {
      const row = document.createElement("tr");
      row.append(cell(group.code));
      row.append(cell(group.name));
      row.append(cell(group.description || "—"));
      const statusCell = document.createElement("td");
      statusCell.append(badge(group.active ? "ACTIVE" : "INACTIVE"));
      row.append(statusCell);
      $("customer-group-rows").append(row);
    }
    $("customer-groups-empty").hidden = result.data.length > 0;
  }

  function openCreateDialog() {
    $("customer-create-error").hidden = true;
    $("customer-create-dialog").showModal();
    $("customer-create-identity-value").focus();
  }

  function openGroupDialog() {
    $("group-create-error").hidden = true;
    $("group-create-dialog").showModal();
    $("group-code").focus();
  }

  $("customer-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    $("customer-create-error").hidden = true;
    const body = {
      company_id: context().company,
      ...Object.fromEntries(new FormData(event.target)),
    };
    const fingerprint = JSON.stringify(body);
    if (lastCreation.body !== fingerprint)
      lastCreation = { body: fingerprint, key: crypto.randomUUID() };
    try {
      const result = await api("customers", {
        method: "POST",
        body,
        key: lastCreation.key,
      });
      $("customer-create-dialog").close();
      event.target.reset();
      lastCreation = { body: "", key: "" };
      await loadDetail(result.customer.id);
      notice("Cliente criado.");
    } catch (error) {
      $("customer-create-error").textContent = error.message;
      $("customer-create-error").hidden = false;
    } finally {
      button.disabled = false;
    }
  });

  $("customer-edit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const tradeName = $("customer-trade-name").value.trim();
      await api(`customers/${current.id}?company_id=${context().company}`, {
        method: "PATCH",
        version: current.version,
        body: {
          legal_name: $("customer-legal-name").value,
          trade_name: tradeName || null,
          status: $("customer-status").value,
        },
      });
      await loadDetail(current.id);
      notice("Cliente atualizado.");
    } finally {
      button.disabled = !can(context().permissions, "update");
    }
  });

  $("customer-assign-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    const groupId =
      $("customer-assign-form").dataset.selectedGroupId ||
      $("customer-assign-group").value;
    try {
      if (!groupId) {
        notice("Selecione um grupo antes de vincular.");
        return;
      }
      await api(`customers/${current.id}/groups`, {
        method: "POST",
        body: {
          company_id: context().company,
          customer_group_id: groupId,
        },
      });
      await loadDetail(current.id);
      notice("Grupo vinculado ao cliente.");
    } finally {
      button.disabled = false;
    }
  });

  $("customer-assign-group").addEventListener("change", () => {
    $("customer-assign-form").dataset.selectedGroupId = $("customer-assign-group").value;
  });

  $("group-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    $("group-create-error").hidden = true;
    try {
      await api("customer-groups", {
        method: "POST",
        body: {
          company_id: context().company,
          code: $("group-code").value,
          name: $("group-name").value,
          description: $("group-description").value.trim() || null,
        },
      });
      $("group-create-dialog").close();
      event.target.reset();
      await showGroups();
      notice("Grupo de clientes criado.");
    } catch (error) {
      $("group-create-error").textContent = error.message;
      $("group-create-error").hidden = false;
    } finally {
      button.disabled = false;
    }
  });

  $("detect-duplicates").addEventListener("click", async () => {
    await api(`customers/${current.id}/duplicates/detect?company_id=${context().company}`, {
      method: "POST",
    });
    await loadDetail(current.id);
    notice("Verificação de duplicidade concluída.");
  });

  $("request-merge").addEventListener("click", async () => {
    const candidateId = $("request-merge").dataset.candidateId;
    if (!candidateId) return;
    await api(`customers/${current.id}/merge-requests`, {
      method: "POST",
      body: {
        company_id: context().company,
        candidate_customer_id: candidateId,
        surviving_customer_id: current.id,
        reason: "Solicitação aberta pela visão Customer 360.",
      },
    });
    await loadDetail(current.id);
    notice("Solicitação de mesclagem registrada.");
  });

  $("customer-status-filter").addEventListener("change", () => {
    page = 1;
    loadList().catch((error) => notice(error.message));
  });
  $("customer-refresh").addEventListener("click", () =>
    loadList().catch((error) => notice(error.message)),
  );
  $("customers-groups-button").addEventListener("click", () =>
    showGroups().catch((error) => notice(error.message)),
  );
  $("new-customer").addEventListener("click", openCreateDialog);
  $("new-group").addEventListener("click", openGroupDialog);
  $("close-customer-create").addEventListener("click", () => $("customer-create-dialog").close());
  $("close-group-create").addEventListener("click", () => $("group-create-dialog").close());
  $("back-customers").addEventListener("click", () => loadList().catch((error) => notice(error.message)));
  $("back-customers-from-groups").addEventListener("click", () =>
    loadList().catch((error) => notice(error.message)),
  );
  $("refresh-customer-detail").addEventListener("click", () => {
    if (current) loadDetail(current.id).catch((error) => notice(error.message));
  });
  $("customer-previous").addEventListener("click", () => {
    page--;
    loadList().catch((error) => notice(error.message));
  });
  $("customer-next").addEventListener("click", () => {
    page++;
    loadList().catch((error) => notice(error.message));
  });

  return { hide, reset, show, showGroups };
}
