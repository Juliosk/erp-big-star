const $ = (id) => document.getElementById(id);

const labels = {
  ACTIVE: "Em análise",
  WAITING: "Aguardando",
  APPROVED: "Aprovada",
  REJECTED: "Rejeitada",
  PENDING: "Pendente",
};

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value;
  return td;
}

function badge(value) {
  const span = document.createElement("span");
  span.className = `status ${value}`;
  span.textContent = labels[value] || value;
  return span;
}

export function mountWorkflow({ api, context, notice, enter }) {
  let selected = null;

  const query = () => `company_id=${encodeURIComponent(context().company)}`;
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("workflow").hidden = true;
  }

  function reset() {
    selected = null;
    hide();
    $("workflow-approval-rows").replaceChildren();
    $("workflow-definition-rows").replaceChildren();
    $("workflow-step-history").replaceChildren();
    $("workflow-decision-form").hidden = true;
    $("workflow-pending-count").textContent = "0";
  }

  function renderDetail(detail) {
    selected = detail;
    const instance = detail.instance;
    $("workflow-selected-title").textContent =
      `${instance.source_module} · ${instance.source_type}`;
    $("workflow-selected-meta").textContent =
      `${instance.status} · v${instance.version} · ${instance.source_id}`;
    $("workflow-step-history").replaceChildren(
      ...detail.steps.map((step) => {
        const item = document.createElement("li");
        item.dataset.status = step.status;
        const marker = document.createElement("span");
        marker.className = "workflow-rail-marker";
        marker.textContent = String(step.sequence).padStart(2, "0");
        const copy = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = step.name;
        const meta = document.createElement("small");
        meta.textContent = `${labels[step.status] || step.status} · ${step.required_permission}`;
        copy.append(title, meta);
        item.append(marker, copy, badge(step.status));
        return item;
      }),
    );
    const active = detail.steps.find((step) => step.status === "ACTIVE");
    $("workflow-decision-form").hidden =
      !active || !can("workflow.approval.decide");
  }

  async function selectApproval(instanceId) {
    const detail = await api(`workflow/instances/${instanceId}?${query()}`);
    renderDetail(detail);
  }

  async function loadApprovals() {
    const result = await api(
      `workflow/approvals/pending?${query()}&page=1&page_size=50`,
    );
    $("workflow-approval-rows").replaceChildren();
    $("workflow-pending-count").textContent = String(result.data.length);
    $("workflow-empty").hidden = result.data.length > 0;
    for (const item of result.data) {
      const row = document.createElement("tr");
      row.append(
        cell(`${item.instance.source_module} / ${item.instance.source_type}`),
        cell(item.step.name),
        cell(`v${item.instance.version}`),
      );
      const action = document.createElement("td");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "quiet";
      open.textContent = "Analisar →";
      open.addEventListener("click", () =>
        selectApproval(item.instance.id).catch((error) => notice(error.message)),
      );
      action.append(open);
      row.append(action);
      $("workflow-approval-rows").append(row);
    }
    if (result.data.length) await selectApproval(result.data[0].instance.id);
  }

  async function loadDefinitions() {
    if (!can("workflow.definition.manage")) {
      $("workflow-definition-form").hidden = true;
      $("workflow-definition-rows").replaceChildren();
      return;
    }
    $("workflow-definition-form").hidden = false;
    const result = await api(`workflow/definitions?${query()}&page=1&page_size=50`);
    $("workflow-definition-rows").replaceChildren(
      ...result.data.map((definition) => {
        const row = document.createElement("tr");
        const identity = document.createElement("td");
        const strong = document.createElement("strong");
        const small = document.createElement("small");
        strong.textContent = definition.code;
        small.textContent = definition.name;
        identity.append(strong, small);
        const state = document.createElement("td");
        state.append(badge(definition.active ? "ACTIVE" : "INACTIVE"));
        row.append(
          identity,
          cell(`${definition.source_module} / ${definition.source_type}`),
          cell(definition.approval_mode),
          state,
        );
        return row;
      }),
    );
  }

  async function show() {
    enter();
    $("workflow").hidden = false;
    await Promise.all([
      can("workflow.request.read") ? loadApprovals() : Promise.resolve(),
      loadDefinitions(),
    ]);
  }

  $("workflow-refresh").addEventListener("click", async () => {
    try {
      await show();
      notice("");
    } catch (error) {
      notice(error.message);
    }
  });

  $("workflow-decision-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const active = selected?.steps.find((step) => step.status === "ACTIVE");
    if (!selected || !active) return;
    const button = event.submitter;
    button.disabled = true;
    try {
      const decision = new FormData(form).get("decision");
      const result = await api(
        `workflow/instances/${selected.instance.id}/decide`,
        {
          method: "POST",
          version: selected.instance.version,
          body: {
            company_id: context().company,
            step_instance_id: active.id,
            decision,
            comment: $("workflow-comment").value.trim() || null,
          },
        },
      );
      renderDetail(result.detail);
      form.reset();
      notice(decision === "APPROVED" ? "Aprovação registrada." : "Rejeição registrada.");
      await loadApprovals();
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  $("workflow-definition-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.submitter;
    button.disabled = true;
    try {
      await api("workflow/definitions", {
        method: "POST",
        body: {
          company_id: context().company,
          code: $("workflow-definition-code").value.trim(),
          name: $("workflow-definition-name").value.trim(),
          source_module: $("workflow-source-module").value.trim(),
          source_type: $("workflow-source-type").value.trim(),
          approval_mode: $("workflow-approval-mode").value,
          steps: [
            {
              sequence: 1,
              code: "STEP-1",
              name: $("workflow-step-name").value.trim(),
              required_permission: $("workflow-step-permission").value.trim(),
              threshold_amount: null,
            },
          ],
        },
      });
      form.reset();
      $("workflow-step-permission").value = "workflow.approval.decide";
      await loadDefinitions();
      notice("Definição de workflow criada.");
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  });

  return { hide, reset, show };
}
