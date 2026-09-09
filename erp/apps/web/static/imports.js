// Same identity and company as the approved catalog. No token or row data in browser storage.
export function mountImports({ api, context, notice, enter }) {
  const $ = (id) => document.getElementById(id);
  let epoch = 0,
    page = 1,
    job = null,
    active = false,
    busy = false;
  let uploadKey = crypto.randomUUID();
  const commitKeys = new Map();
  const status = {
    UPLOADED: "Arquivo recebido",
    VALIDATED: "Validação concluída",
    REJECTED: "Carga rejeitada — nenhum produto alterado",
    PREVIEWED: "Preview pronto para revisão",
    CONFIRMED: "Confirmado — aguardando gravação",
    COMMITTED: "Importação concluída",
    CANCELLED: "Importação cancelada",
  };
  const actionLabels = {
    validate: "Validar arquivo",
    preview: "Abrir preview",
    confirm: "Confirmar preview",
    commit: "Gravar todos os produtos",
    cancel: "Cancelar importação",
  };
  const query = () => `company_id=${context().company}`;
  function cell(row, value) {
    const td = document.createElement("td");
    td.textContent = value;
    row.append(td);
  }
  function reset() {
    epoch++;
    active = false;
    busy = false;
    page = 1;
    job = null;
    $("imports").hidden = true;
    $("import-job").hidden = true;
    $("import-upload-form").reset();
    uploadKey = crypto.randomUUID();
    commitKeys.clear();
    for (const id of [
      "import-preview-rows",
      "import-history",
      "import-actions",
      "import-template",
    ])
      $(id).replaceChildren();
    for (const id of [
      "import-job-title",
      "import-job-status",
      "import-job-version",
      "import-fingerprint",
    ])
      $(id).textContent = "";
  }
  async function run(action) {
    if (busy) return;
    const started = epoch;
    busy = true;
    $("imports").setAttribute("aria-busy", "true");
    $("imports")
      .querySelectorAll("button")
      .forEach((button) => (button.disabled = true));
    try {
      await action(started);
    } catch (error) {
      if (started === epoch) notice(error.message);
    } finally {
      if (started === epoch) {
        busy = false;
        $("imports").removeAttribute("aria-busy");
        refreshControls();
      }
    }
  }
  function refreshControls() {
    $("imports")
      .querySelectorAll("button")
      .forEach((button) => (button.disabled = false));
    $("import-download").disabled = !$("import-template").value;
    $("import-upload").disabled = !$("import-template").value;
    $("import-previous").disabled = page === 1;
    $("import-next").disabled = $("import-history").children.length < 20;
  }
  async function templates(started) {
    const result = await api(`data/import-templates?${query()}`);
    if (started !== epoch) return;
    $("import-template").replaceChildren(
      ...result.items.map(
        (item) => new Option(`${item.name} · versão 1`, item.id),
      ),
    );
    $("import-provision").hidden =
      !context().permissions.has("data.import.confirm") ||
      result.items.some((item) => item.code === "PRODUCTS_V1");
  }
  async function history(started) {
    const result = await api(`data/imports?${query()}&page=${page}`);
    if (started !== epoch) return;
    $("import-history").replaceChildren();
    for (const item of result.items) {
      const row = document.createElement("tr");
      cell(row, item.filename);
      cell(row, status[item.status]);
      cell(row, item.version);
      const td = document.createElement("td"),
        button = document.createElement("button");
      button.className = "quiet";
      button.textContent = "Abrir";
      button.setAttribute("aria-label", `Abrir importação ${item.filename}`);
      button.onclick = () =>
        run(async (ticket) => {
          const data = await api(`data/imports/${item.id}?${query()}`);
          if (ticket === epoch) render(data);
        });
      td.append(button);
      row.append(td);
      $("import-history").append(row);
    }
    $("import-page").textContent = `Página ${page}`;
  }
  function render(data) {
    const step = {
      UPLOADED: 0,
      REJECTED: 1,
      VALIDATED: 1,
      PREVIEWED: 2,
      CONFIRMED: 3,
      COMMITTED: 4,
    }[data.status];
    $("import-track")
      .querySelectorAll("li")
      .forEach((item, index) => {
        if (index === step) item.setAttribute("aria-current", "step");
        else item.removeAttribute("aria-current");
      });
    job = data;
    $("import-job").hidden = false;
    $("import-job-title").textContent = data.filename;
    $("import-job-status").textContent =
      `${status[data.status]}${data.error_count ? ` · ${data.error_count} linha(s) com erro` : ""}${data.count !== undefined ? ` · ${data.count} produto(s) alterado(s)` : ""}`;
    $("import-job-version").textContent = `Versão ${data.version}`;
    $("import-fingerprint").textContent = data.fingerprint
      ? `Fingerprint do preview: ${data.fingerprint}`
      : "";
    $("import-preview-rows").replaceChildren();
    for (const item of data.rows || []) {
      const row = document.createElement("tr");
      const describe = (values) =>
        values
          ? `${values.code} · ${values.name} · ${values.product_type} / ${values.uom}`
          : "Novo produto";
      cell(row, `${item.number} / ${item.proposed.sku || "Sem SKU"}`);
      cell(
        row,
        { CREATE: "Criar", UPDATE: "Atualizar", UNCHANGED: "Sem alteração" }[
          item.action
        ],
      );
      cell(row, describe(item.current));
      cell(row, describe(item.proposed));
      cell(row, [...item.differences, ...item.errors].join("; ") || "—");
      if (item.errors.length) row.className = "import-invalid";
      $("import-preview-rows").append(row);
    }
    $("import-actions").replaceChildren();
    const actions =
      {
        UPLOADED: ["validate", "cancel"],
        REJECTED: ["validate", "cancel"],
        VALIDATED: ["preview", "validate", "cancel"],
        PREVIEWED: ["confirm", "validate", "cancel"],
        CONFIRMED: ["commit", "validate", "cancel"],
      }[data.status] || [];
    for (const action of actions) {
      if (
        ["confirm", "commit"].includes(action) &&
        !context().permissions.has("data.import.confirm")
      )
        continue;
      const button = document.createElement("button");
      button.textContent = actionLabels[action];
      button.disabled = busy;
      button.onclick = () =>
        run(async (ticket) => {
          const snapshot = job,
            signature = `${snapshot.id}:${snapshot.version}`;
          if (!commitKeys.has(signature))
            commitKeys.set(signature, crypto.randomUUID());
          const result = await api(
            `data/imports/${snapshot.id}/${action}?${query()}`,
            {
              method: "POST",
              version: snapshot.version,
              key: commitKeys.get(signature),
              body: { fingerprint: snapshot.fingerprint || "" },
            },
          );
          if (ticket !== epoch) return;
          render(result);
          await history(ticket);
          notice("");
        });
      $("import-actions").append(button);
    }
    if (data.error_count) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.textContent = "Baixar inconsistências";
      button.disabled = busy;
      button.onclick = () =>
        run(async (ticket) =>
          save(
            await api(`data/imports/${data.id}/rejected-file?${query()}`, {
              binary: true,
            }),
            "inconsistencias.xlsx",
            ticket,
          ),
        );
      $("import-actions").append(button);
    }
  }
  function save(blob, filename, ticket) {
    if (ticket !== epoch) return;
    const url = URL.createObjectURL(blob),
      anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function show() {
    if (!context().company) return;
    reset();
    enter();
    active = true;
    $("imports").hidden = false;
    await run(async (ticket) => {
      await templates(ticket);
      if (ticket === epoch) await history(ticket);
    });
  }
  $("import-file").onchange = () => {
    uploadKey = crypto.randomUUID();
  };
  $("import-upload-form").onsubmit = (event) => {
    event.preventDefault();
    run(async (ticket) => {
      const file = $("import-file").files[0];
      if (!file || file.size > 10 * 1024 * 1024)
        throw new Error("Escolha um XLSX de até 10 MiB.");
      const result = await api(
        `data/imports?${query()}&template_id=${$("import-template").value}&filename=${encodeURIComponent(file.name)}`,
        { method: "POST", raw: file, key: uploadKey },
      );
      if (ticket !== epoch) return;
      render(result);
      await history(ticket);
      notice("");
    });
  };
  $("import-provision").onclick = () =>
    run(async (ticket) => {
      await api(`data/import-templates/product?${query()}`, { method: "POST" });
      if (ticket === epoch) await templates(ticket);
    });
  $("import-download").onclick = () =>
    run(async (ticket) =>
      save(
        await api(
          `data/import-templates/${$("import-template").value}/download-model?${query()}`,
          { binary: true },
        ),
        "produtos-v1.xlsx",
        ticket,
      ),
    );
  $("import-refresh").onclick = () =>
    run(async (ticket) => {
      await history(ticket);
      if (job && ticket === epoch) {
        const data = await api(`data/imports/${job.id}?${query()}`);
        if (ticket === epoch) render(data);
      }
    });
  $("import-previous").onclick = () =>
    run(async (ticket) => {
      page--;
      await history(ticket);
    });
  $("import-next").onclick = () =>
    run(async (ticket) => {
      page++;
      await history(ticket);
    });
  return {
    reset,
    show,
    get active() {
      return active;
    },
  };
}
