const $ = (id) => document.getElementById(id);

const can = (permissions, permission) => permissions.has(permission);
const compact = (value) => (value ? `${value}`.slice(0, 8) : "—");

function text(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function cell(value) {
  const td = document.createElement("td");
  if (value instanceof Node) td.append(value);
  else td.textContent = text(value);
  return td;
}

function badge(value) {
  const span = document.createElement("span");
  span.className = `status ${value}`;
  span.textContent = value;
  return span;
}

function setDisabled(form, disabled) {
  for (const element of form.querySelectorAll("input, select, button")) {
    element.disabled = disabled;
  }
}

export function mountWms({ api, context, notice, enter }) {
  let selectedWave = null;
  let selectedPackage = null;

  const query = () => `company_id=${context().company}`;

  function hide() {
    $("wms").hidden = true;
  }

  function reset() {
    hide();
    selectedWave = null;
    selectedPackage = null;
    $("wms-wave-form").reset();
    $("wms-scan-form").reset();
    $("wms-package-form").reset();
    $("wms-package-item-form").reset();
    $("wms-wave-quantity").value = "1";
    $("wms-scan-quantity").value = "1";
    $("wms-package-quantity").value = "1";
    $("wms-selected-title").textContent = "Nenhuma onda selecionada";
    $("wms-selected-meta").textContent =
      "Selecione uma onda para liberar, bipar e embalar.";
    $("wms-wave-rows").replaceChildren();
    $("wms-task-rows").replaceChildren();
    $("wms-package-card").replaceChildren();
    $("wms-package-card").hidden = true;
    $("wms-empty").hidden = true;
  }

  async function show() {
    enter();
    $("wms").hidden = false;
    const { permissions } = context();
    const allowed = can(permissions, "wms.pick.execute") || can(permissions, "wms.pack.execute");
    $("wms-wave-form").hidden = !allowed;
    $("wms-scan-form").hidden = !can(permissions, "wms.pick.execute");
    $("wms-package-form").hidden = !can(permissions, "wms.pack.execute");
    $("wms-package-item-form").hidden = !can(permissions, "wms.pack.execute");
    $("wms-package-verify").hidden = !can(permissions, "wms.pack.execute");
    $("wms-package-finalize").hidden = !can(permissions, "wms.pack.execute");
    await loadWaves();
  }

  function renderSelected(detail) {
    selectedWave = detail;
    const wave = detail?.wave;
    if (!wave) {
      $("wms-selected-title").textContent = "Nenhuma onda selecionada";
      $("wms-selected-meta").textContent =
        "Selecione uma onda para liberar, bipar e embalar.";
      $("wms-task-rows").replaceChildren();
      return;
    }
    $("wms-selected-title").textContent = wave.code;
    $("wms-selected-meta").textContent = `${wave.status} · versão ${wave.version} · ${compact(wave.id)}`;
    $("wms-task-rows").replaceChildren(
      ...detail.tasks.map((task) =>
        rowTask(task),
      ),
    );
    const firstOpenTask = detail.tasks.find((task) => task.status !== "COMPLETED");
    const task = firstOpenTask || detail.tasks[0];
    if (task) {
      $("wms-scan-task-id").value = task.id;
      $("wms-package-task-id").value = task.id;
      $("wms-product-id").value ||= task.product_id;
      $("wms-package-product-id").value = task.product_id;
    }
  }

  function rowTask(task) {
    const tr = document.createElement("tr");
    tr.append(
      cell(task.sequence),
      cell(compact(task.product_id)),
      cell(`${task.picked_quantity} / ${task.requested_quantity}`),
    );
    const statusCell = cell("");
    statusCell.append(badge(task.status));
    tr.append(statusCell);
    return tr;
  }

  async function selectWave(id) {
    const detail = await api(`wms/picking-waves/${id}?${query()}`);
    renderSelected(detail);
  }

  async function loadWaves() {
    const result = await api(`wms/picking-waves?${query()}&page=1&page_size=50`);
    $("wms-wave-rows").replaceChildren();
    for (const wave of result.data) {
      const tr = document.createElement("tr");
      tr.append(cell(wave.code));
      const statusCell = cell("");
      statusCell.append(badge(wave.status));
      tr.append(statusCell, cell(`v${wave.version}`));
      const action = document.createElement("td");
      const open = document.createElement("button");
      open.className = "quiet";
      open.type = "button";
      open.textContent = "Abrir";
      open.addEventListener("click", () =>
        selectWave(wave.id).catch((error) => notice(error.message)),
      );
      const release = document.createElement("button");
      release.className = "quiet";
      release.type = "button";
      release.textContent = "Liberar";
      release.disabled = wave.status !== "DRAFT";
      release.addEventListener("click", async () => {
        release.disabled = true;
        try {
          const released = await api(`wms/picking-waves/${wave.id}/release?${query()}`, {
            method: "POST",
            version: wave.version,
          });
          notice("Onda liberada para separação.");
          renderSelected(released.detail);
          await loadWaves();
        } catch (error) {
          notice(error.message);
          release.disabled = false;
        }
      });
      action.append(open, release);
      tr.append(action);
      $("wms-wave-rows").append(tr);
    }
    $("wms-empty").hidden = result.data.length > 0;
    if (!selectedWave && result.data.length) await selectWave(result.data[0].id);
  }

  function renderPackage(detail) {
    selectedPackage = detail;
    const packageData = detail.package;
    $("wms-package-card").hidden = false;
    $("wms-package-card").replaceChildren();
    const title = document.createElement("strong");
    title.textContent = `${packageData.package_code} · ${packageData.status} · v${packageData.version}`;
    const items = document.createElement("p");
    items.textContent = `${detail.items.length} item(ns) embalado(s)`;
    $("wms-package-card").append(title, items);
  }

  $("wms-refresh").addEventListener("click", async () => {
    try {
      await loadWaves();
      notice("");
    } catch (error) {
      notice(error.message);
    }
  });

  $("wms-wave-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setDisabled(form, true);
    try {
      const result = await api("wms/picking-waves", {
        body: {
          code: $("wms-wave-code").value.trim(),
          company_id: context().company,
          items: [
            {
              product_id: $("wms-product-id").value.trim(),
              quantity: $("wms-wave-quantity").value,
            },
          ],
        },
        method: "POST",
      });
      form.reset();
      $("wms-wave-quantity").value = "1";
      renderSelected(result);
      await loadWaves();
      notice("Onda de separação criada.");
    } catch (error) {
      notice(error.message);
    } finally {
      setDisabled(form, false);
    }
  });

  $("wms-scan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setDisabled(form, true);
    try {
      const result = await api(`wms/picking-tasks/${$("wms-scan-task-id").value.trim()}/scan?${query()}`, {
        body: {
          barcode: $("wms-scan-barcode").value.trim(),
          quantity: $("wms-scan-quantity").value,
        },
        key: crypto.randomUUID(),
        method: "POST",
      });
      await selectWave(result.task.wave_id);
      notice("Tarefa bipada e quantidade separada atualizada.");
    } catch (error) {
      notice(error.message);
    } finally {
      setDisabled(form, false);
    }
  });

  $("wms-package-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setDisabled(form, true);
    try {
      const weight = $("wms-package-weight").value;
      const result = await api("wms/packages", {
        body: {
          company_id: context().company,
          package_code: $("wms-package-code").value.trim(),
          package_type: $("wms-package-type").value,
          wave_id: selectedWave?.wave?.id || null,
          weight_grams: weight ? Number(weight) : null,
        },
        method: "POST",
      });
      form.reset();
      renderPackage(result);
      notice("Pacote criado para embalagem.");
    } catch (error) {
      notice(error.message);
    } finally {
      setDisabled(form, false);
    }
  });

  $("wms-package-item-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedPackage) {
      notice("Crie um pacote antes de adicionar itens.");
      return;
    }
    const form = event.currentTarget;
    setDisabled(form, true);
    try {
      const result = await api(`wms/packages/${selectedPackage.package.id}/items?${query()}`, {
        body: {
          product_id: $("wms-package-product-id").value.trim(),
          quantity: $("wms-package-quantity").value,
          task_id: $("wms-package-task-id").value.trim(),
        },
        method: "POST",
      });
      renderPackage(result);
      notice("Item adicionado ao pacote.");
    } catch (error) {
      notice(error.message);
    } finally {
      setDisabled(form, false);
    }
  });

  $("wms-package-verify").addEventListener("click", async () => {
    if (!selectedPackage) return notice("Crie um pacote antes de verificar.");
    try {
      const result = await api(`wms/packages/${selectedPackage.package.id}/verify?${query()}`, {
        method: "POST",
        version: selectedPackage.package.version,
      });
      renderPackage(result);
      notice("Pacote verificado.");
    } catch (error) {
      notice(error.message);
    }
  });

  $("wms-package-finalize").addEventListener("click", async () => {
    if (!selectedPackage) return notice("Verifique o pacote antes de finalizar.");
    try {
      const result = await api(`wms/packages/${selectedPackage.package.id}/finalize?${query()}`, {
        method: "POST",
        version: selectedPackage.package.version,
      });
      renderPackage(result);
      notice("Pacote finalizado para expedição.");
    } catch (error) {
      notice(error.message);
    }
  });

  return { hide, reset, show };
}
