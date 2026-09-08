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
};
let token = "",
  permissions = new Set(),
  company = "",
  page = 1,
  current = null,
  generation = 0;
let lastCreation = { body: "", key: "" };
const can = (action) => permissions.has(`product.product.${action}`);
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}
function reset() {
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
async function api(path, { method = "GET", body, version, key } = {}) {
  const requestToken = token;
  const headers = { Authorization: `Bearer ${requestToken}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (version !== undefined) headers["If-Match"] = `"${version}"`;
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new Error(
      "Não foi possível conectar. Verifique a aplicação e tente novamente.",
    );
  }
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && requestToken === token) reset();
    const code = result.error?.code || "UNKNOWN";
    const trace = result.error?.correlation_id;
    throw new Error(
      `${errors[code] || "Não foi possível concluir a operação."}${trace ? ` Referência: ${trace}` : ""}`,
    );
  }
  return result;
}
function bind(id, action, event = "click") {
  $(id).addEventListener(event, async (e) => {
    e.preventDefault();
    try {
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
  if (!company) {
    notice(
      "Nenhuma empresa ativa autorizada. Configure os escopos da identidade.",
    );
    return;
  }
  notice("");
  page = 1;
  await loadList();
}
async function loadList() {
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
