const $ = (id) => document.getElementById(id);

const stateLabels = {
  PENDING: "Pendente",
  MATCHED: "Conciliado",
  AMBIGUOUS: "Ambíguo",
  UNMATCHED: "Sem candidato",
  DIRECT_FEE: "Lançamento direto",
};

const reasonLabels = {
  EXACT_MATCH: "Documento, valor e data coincidem com o lançamento financeiro.",
  FUZZY_MATCH: "Valor e data estão dentro da janela de tolerância configurada.",
  DOCUMENT_MISMATCH: "O documento bancário diverge do documento financeiro.",
  AMOUNT_MISMATCH: "O valor bancário diverge do valor esperado no ERP.",
  DATE_MISMATCH: "A data está fora da janela de tolerância.",
  DIRECTION_MISMATCH: "A natureza de crédito/débito não corresponde ao candidato.",
  NO_CANDIDATE: "Nenhum título elegível foi encontrado para esta linha.",
  MULTIPLE_CANDIDATES: "Mais de um candidato possui evidência semelhante.",
};

const money = (value) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
    Number(value || 0),
  );

function shortDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(
    new Date(`${value}T12:00:00Z`),
  );
}

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

function shortId(value) {
  return String(value || "—").slice(0, 8);
}

async function busy(button, callback) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    return await callback();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

export function mountBankConciliation({ api, context, notice, enter }) {
  let statements = [];
  let movements = [];
  let outcomes = new Map();
  let selectedMovement = null;
  let selectedStatement = null;
  let candidates = [];
  let page = 1;
  let hasMore = false;
  let directConfirmed = new Set();
  const can = (permission) => context().permissions.has(permission);

  function hide() {
    $("bank-conciliation").hidden = true;
    $("conciliation-nav").removeAttribute("aria-current");
    if (
      window.location.pathname
        .replace(/\/$/, "")
        .endsWith("/finance/conciliation")
    ) {
      history.replaceState({}, "", "/ui/");
    }
  }

  function reset() {
    hide();
    statements = [];
    movements = [];
    outcomes = new Map();
    selectedMovement = null;
    selectedStatement = null;
    candidates = [];
    page = 1;
    hasMore = false;
    directConfirmed = new Set();
    $("conciliation-upload-form").reset();
    $("conciliation-statement-list").replaceChildren();
    $("conciliation-movement-list").replaceChildren();
    $("conciliation-candidate-list").replaceChildren();
    $("conciliation-dossier-empty").hidden = false;
    $("conciliation-dossier-content").hidden = true;
    if ($("conciliation-resolution-dialog").open) {
      $("conciliation-resolution-dialog").close();
    }
  }

  function statementFor(movement) {
    return statements.find((item) => item.id === movement.statement_id);
  }

  function outcomeFor(movementId) {
    return outcomes.get(movementId) || null;
  }

  function classification(movement) {
    if (movement.status === "RECONCILED") return "MATCHED";
    const outcome = outcomeFor(movement.id);
    if (outcome?.classification === "AMBIGUOUS") return "AMBIGUOUS";
    if (outcome?.classification?.startsWith("DIRECT_")) return "DIRECT_FEE";
    if (outcome?.reason === "NO_CANDIDATE") return "UNMATCHED";
    if (["FEE", "INTEREST", "TAX"].includes(movement.kind)) return "DIRECT_FEE";
    return "PENDING";
  }

  function filteredMovements() {
    const state = $("conciliation-state-filter").value;
    const account = $("conciliation-account-filter").value;
    const from = $("conciliation-period-from").value;
    const to = $("conciliation-period-to").value;
    return movements.filter((movement) => {
      const statement = statementFor(movement);
      return (
        (!state || classification(movement) === state) &&
        (!account || statement?.bank_account_id === account) &&
        (!from || movement.booked_on >= from) &&
        (!to || movement.booked_on <= to)
      );
    });
  }

  function renderMetrics() {
    const filtered = filteredMovements();
    $("conciliation-statement-count").textContent = String(statements.length);
    $("conciliation-movement-count").textContent = String(filtered.length);
    $("conciliation-pending-count").textContent = String(
      filtered.filter((item) => classification(item) !== "MATCHED").length,
    );
    $("conciliation-matched-count").textContent = String(
      filtered.filter((item) => classification(item) === "MATCHED").length,
    );
  }

  function renderStatements() {
    const list = $("conciliation-statement-list");
    list.replaceChildren();
    const currentAccounts = new Set();
    for (const statement of statements) {
      currentAccounts.add(statement.bank_account_id);
      const button = node("button", "conciliation-statement-card");
      button.type = "button";
      button.dataset.statementId = statement.id;
      if (selectedStatement?.id === statement.id) {
        button.setAttribute("aria-current", "true");
      }
      button.append(
        node("strong", "", `${statement.bank_code} · ${statement.account_reference}`),
        node(
          "span",
          "",
          `${shortDate(statement.period_start)} — ${shortDate(statement.period_end)}`,
        ),
        node(
          "small",
          "",
          `${statement.pending_count} pendentes · ${statement.reconciled_count} conciliados`,
        ),
      );
      button.addEventListener("click", async () => {
        $("conciliation-account-filter").value = statement.bank_account_id;
        page = 1;
        await loadMovements();
      });
      list.append(button);
    }
    const account = $("conciliation-account-filter");
    const previous = account.value;
    account.replaceChildren(new Option("Todas", ""));
    for (const accountId of currentAccounts) {
      const statement = statements.find((item) => item.bank_account_id === accountId);
      account.add(
        new Option(
          `${statement?.bank_code || "Banco"} · ${statement?.account_reference || shortId(accountId)}`,
          accountId,
        ),
      );
    }
    if (currentAccounts.has(previous)) account.value = previous;
  }

  function movementCard(movement) {
    const state = classification(movement);
    const card = node("button", `conciliation-movement-card ${state}`);
    card.type = "button";
    card.dataset.movementId = movement.id;
    if (selectedMovement?.id === movement.id) {
      card.setAttribute("aria-current", "true");
    }
    card.append(
      node("strong", "", movement.description || "Movimento bancário"),
      node("span", "amount", money(movement.amount)),
      node(
        "small",
        "",
        `${shortDate(movement.booked_on)} · ${movement.document_number || movement.external_id}`,
      ),
      node("span", `conciliation-state-pill ${state}`, stateLabels[state]),
    );
    card.addEventListener("click", () => openMovement(movement));
    return card;
  }

  function renderMovements() {
    const filtered = filteredMovements();
    const list = $("conciliation-movement-list");
    list.replaceChildren(...filtered.map(movementCard));
    $("conciliation-empty").hidden = filtered.length > 0;
    $("conciliation-queue-page").textContent = `Página ${page}`;
    $("conciliation-previous").disabled = page <= 1;
    $("conciliation-next").disabled = !hasMore;
    renderMetrics();
  }

  function renderFacts(movement, statement) {
    const facts = [
      ["Data", shortDate(movement.booked_on)],
      ["Natureza", movement.direction === "DEBIT" ? "Débito" : "Crédito"],
      ["Tipo", movement.kind],
      ["Documento", movement.document_number || "Não informado"],
      ["Conta", `${statement.bank_code} · ${statement.account_reference}`],
      ["ID externo", movement.external_id],
    ];
    $("conciliation-bank-details").replaceChildren(
      ...facts.map(([label, value]) => {
        const wrapper = node("div");
        wrapper.append(node("dt", "", label), node("dd", "", value));
        return wrapper;
      }),
    );
  }

  function renderCandidates() {
    const list = $("conciliation-candidate-list");
    if (!candidates.length) {
      list.replaceChildren(
        node("p", "hint", "Nenhum candidato financeiro elegível foi encontrado."),
      );
      return;
    }
    list.replaceChildren(
      ...candidates.map((candidate) => {
        const card = node("article", "conciliation-candidate-card");
        card.dataset.candidateId = candidate.reference_id;
        card.append(
          node(
            "strong",
            "",
            `${candidate.source} · ${candidate.document_number || shortId(candidate.reference_id)}`,
          ),
          node("span", "score", `${Math.round(Number(candidate.score) * 100)}%`),
          node(
            "small",
            "",
            `${money(candidate.amount)} · ${shortDate(candidate.expected_on)} · ${reasonLabels[candidate.reason] || candidate.reason}`,
          ),
        );
        return card;
      }),
    );
  }

  function explanation(state, outcome, candidate) {
    if (state === "MATCHED") {
      return [
        "Evidência financeira vinculada",
        "A linha bancária foi conciliada e mantém o vínculo auditável com o lançamento do ERP.",
      ];
    }
    if (state === "AMBIGUOUS") {
      return [
        "Há mais de um candidato plausível",
        "Compare documento, data e valor antes de escolher o lançamento correto.",
      ];
    }
    if (state === "UNMATCHED") {
      return [
        "Nenhum título compatível",
        "Revise os dados do extrato ou classifique a linha como lançamento direto com justificativa.",
      ];
    }
    if (state === "DIRECT_FEE") {
      return [
        "Movimento operacional bancário",
        "A natureza da linha indica tarifa, juros ou imposto e pode ser classificada diretamente.",
      ];
    }
    if (candidate?.automatic) {
      return ["Sugestão exata", reasonLabels[candidate.reason] || candidate.reason];
    }
    if (outcome?.reason) {
      return ["Análise concluída", reasonLabels[outcome.reason] || outcome.reason];
    }
    return [
      "Aguardando decisão",
      "A análise não encontrou uma decisão automática. Consulte os candidatos disponíveis.",
    ];
  }

  function renderDossier() {
    if (!selectedMovement || !selectedStatement) return;
    const movement = selectedMovement;
    const state = classification(movement);
    const outcome = outcomeFor(movement.id);
    const candidate =
      candidates.find((item) => item.reference_id === movement.matched_reference_id) ||
      candidates.find((item) => item.automatic) ||
      candidates[0];
    $("conciliation-dossier-empty").hidden = true;
    $("conciliation-dossier-content").hidden = false;
    $("conciliation-selected-title").textContent = movement.description;
    $("conciliation-selected-meta").textContent =
      `${shortDate(movement.booked_on)} · linha ${shortId(movement.id)}`;
    $("conciliation-selected-version").textContent = `v${selectedStatement.version}`;
    $("conciliation-bank-value").textContent = money(movement.amount);
    $("conciliation-bank-document").textContent =
      movement.document_number || movement.external_id;
    $("conciliation-erp-value").textContent = candidate
      ? money(candidate.amount)
      : "Sem candidato";
    $("conciliation-erp-document").textContent = candidate
      ? `${candidate.source} · ${candidate.document_number || shortId(candidate.reference_id)}`
      : "—";
    const signal = $("conciliation-match-signal");
    signal.className = `conciliation-match-signal ${state}`;
    signal.querySelector("strong").textContent = stateLabels[state];
    signal.querySelector("small").textContent = candidate
      ? `${Math.round(Number(candidate.score) * 100)}% de aderência`
      : "sem evidência vinculada";
    const [title, text] = explanation(state, outcome, candidate);
    $("conciliation-explanation-title").textContent = title;
    $("conciliation-explanation-text").textContent = text;
    const mutable =
      movement.status !== "RECONCILED" &&
      !directConfirmed.has(movement.id) &&
      can("finance.reconciliation.execute");
    $("conciliation-accept").hidden = !mutable || !candidate?.automatic;
    $("conciliation-resolve").hidden = !mutable || !candidates.length;
    $("conciliation-direct").hidden = !mutable;
    renderFacts(movement, selectedStatement);
    renderCandidates();
    renderStatements();
    renderMovements();
  }

  async function loadStatements() {
    const { company } = context();
    const result = await api(
      `finance/reconciliation/statements?company_id=${company}&page=1&page_size=100`,
    );
    statements = result.data;
    renderStatements();
  }

  async function loadMovements() {
    const { company } = context();
    const state = $("conciliation-state-filter").value;
    const backendStatus = state === "MATCHED" ? "RECONCILED" : state ? "PENDING" : "";
    const result = await api(
      `finance/reconciliation/movements?company_id=${company}&page=${page}&page_size=50${backendStatus ? `&status=${backendStatus}` : ""}`,
    );
    movements = result.data;
    hasMore = result.has_more;
    renderMovements();
  }

  async function openMovement(movement) {
    selectedMovement = movement;
    const { company } = context();
    const detail = await api(
      `finance/reconciliation/statements/${movement.statement_id}?company_id=${company}`,
    );
    selectedStatement = detail.statement;
    selectedMovement = detail.movements.find((item) => item.id === movement.id) || movement;
    const current = statements.findIndex((item) => item.id === selectedStatement.id);
    if (current >= 0) statements[current] = selectedStatement;
    if (
      selectedMovement.status !== "RECONCILED" &&
      can("finance.reconciliation.execute")
    ) {
      const analysis = await api(
        `finance/reconciliation/statements/${selectedStatement.id}/match?company_id=${company}`,
        { method: "POST", body: { mode: "SIMULATE" }, version: selectedStatement.version },
      );
      selectedStatement = analysis.statement;
      for (const item of analysis.outcomes) outcomes.set(item.movement_id, item);
    }
    const options = await api(
      `finance/reconciliation/statements/${selectedStatement.id}/movements/${selectedMovement.id}/candidates?company_id=${company}`,
    );
    candidates = options.data;
    renderDossier();
  }

  function openResolution(mode) {
    const direct = mode === "DIRECT_ENTRY";
    const dialog = $("conciliation-resolution-dialog");
    dialog.dataset.mode = mode;
    $("conciliation-dialog-title").textContent = direct
      ? "Classificar lançamento direto"
      : "Resolver movimento manualmente";
    $("conciliation-dialog-context").textContent = selectedMovement
      ? `${selectedMovement.description} · ${money(selectedMovement.amount)}`
      : "";
    $("conciliation-candidate-options").hidden = direct;
    $("conciliation-candidate-options").replaceChildren(
      node("legend", "", "Escolha o candidato financeiro"),
      ...candidates.map((candidate, index) => {
        const label = node("label", "candidate-option");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "conciliation-candidate";
        input.value = candidate.reference_id;
        input.checked = index === 0;
        label.append(
          input,
          node(
            "span",
            "",
            `${candidate.source} · ${candidate.document_number || shortId(candidate.reference_id)}`,
          ),
          node("strong", "", money(candidate.amount)),
        );
        return label;
      }),
    );
    $("conciliation-justification").value = "";
    $("conciliation-dialog-error").hidden = true;
    dialog.showModal();
    if (direct) $("conciliation-justification").focus();
  }

  async function resolveMovement(mode, candidateId, justification) {
    if (!selectedMovement || !selectedStatement) return;
    const { company } = context();
    const result = await api(
      `finance/reconciliation/statements/${selectedStatement.id}/movements/${selectedMovement.id}/resolve?company_id=${company}`,
      {
        method: "POST",
        version: selectedStatement.version,
        body: {
          mode,
          candidate_id: candidateId || null,
          justification: justification || null,
        },
      },
    );
    if (mode === "DIRECT_ENTRY") {
      directConfirmed.add(selectedMovement.id);
      for (const item of result.outcomes) outcomes.set(item.movement_id, item);
    }
    const movementId = selectedMovement.id;
    await loadStatements();
    await loadMovements();
    const refreshed = movements.find((item) => item.id === movementId);
    if (refreshed) await openMovement(refreshed);
    else {
      selectedMovement = null;
      selectedStatement = null;
      candidates = [];
      $("conciliation-dossier-empty").hidden = false;
      $("conciliation-dossier-content").hidden = true;
    }
    notice(
      mode === "DIRECT_ENTRY"
        ? "Classificação direta confirmada, sem criar vínculo artificial com um título."
        : "Movimento conciliado com trilha de decisão registrada.",
    );
  }

  async function uploadStatement(event) {
    event.preventDefault();
    const file = $("conciliation-file").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("company_id", context().company);
    form.append("bank_account_id", $("conciliation-bank-account").value.trim());
    form.append("source", $("conciliation-source").value);
    form.append("bank_code", $("conciliation-bank-code").value.trim());
    form.append(
      "account_reference",
      $("conciliation-account-reference").value.trim(),
    );
    form.append("file", file);
    const result = await busy($("conciliation-upload"), () =>
      api("finance/reconciliation/statements/upload", { method: "POST", form }),
    );
    $("conciliation-import-status").textContent =
      `Extrato ${result.statement.bank_code} · ${result.statement.account_reference} importado com ${result.movements.length} movimentos.`;
    $("conciliation-upload-form").reset();
    page = 1;
    await loadStatements();
    await loadMovements();
  }

  async function show() {
    if (!can("finance.reconciliation.read")) return;
    enter();
    history.replaceState({}, "", "/ui/finance/conciliation");
    $("bank-conciliation").hidden = false;
    $("conciliation-nav").setAttribute("aria-current", "page");
    await loadStatements();
    await loadMovements();
  }

  $("conciliation-upload-form").addEventListener("submit", async (event) => {
    try {
      await uploadStatement(event);
    } catch (error) {
      $("conciliation-import-status").textContent = error.message;
    }
  });
  $("conciliation-refresh").addEventListener("click", async () => {
    try {
      await loadStatements();
      await loadMovements();
      notice("");
    } catch (error) {
      notice(error.message);
    }
  });
  [
    "conciliation-state-filter",
    "conciliation-account-filter",
    "conciliation-period-from",
    "conciliation-period-to",
  ].forEach((id) =>
    $(id).addEventListener("change", async () => {
      page = 1;
      if (id === "conciliation-state-filter") await loadMovements();
      else renderMovements();
    }),
  );
  $("conciliation-previous").addEventListener("click", async () => {
    if (page > 1) {
      page -= 1;
      await loadMovements();
    }
  });
  $("conciliation-next").addEventListener("click", async () => {
    if (hasMore) {
      page += 1;
      await loadMovements();
    }
  });
  $("conciliation-accept").addEventListener("click", async () => {
    const candidate = candidates.find((item) => item.automatic);
    if (!candidate) return;
    try {
      await busy($("conciliation-accept"), () =>
        resolveMovement("ACCEPT_MATCH", candidate.reference_id, null),
      );
    } catch (error) {
      notice(error.message);
    }
  });
  $("conciliation-resolve").addEventListener("click", () =>
    openResolution("FORCE_MATCH"),
  );
  $("conciliation-direct").addEventListener("click", () =>
    openResolution("DIRECT_ENTRY"),
  );
  $("conciliation-dialog-close").addEventListener("click", () =>
    $("conciliation-resolution-dialog").close(),
  );
  $("conciliation-resolution-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const dialog = $("conciliation-resolution-dialog");
    const mode = dialog.dataset.mode;
    const candidateId =
      mode === "DIRECT_ENTRY"
        ? undefined
        : dialog.querySelector('input[name="conciliation-candidate"]:checked')
            ?.value;
    const justification = $("conciliation-justification").value.trim();
    const error = $("conciliation-dialog-error");
    if (!justification) {
      error.textContent = "Informe a evidência que justifica esta decisão manual.";
      error.hidden = false;
      return;
    }
    if (mode !== "DIRECT_ENTRY" && !candidateId) {
      error.textContent = "Selecione o candidato financeiro correto.";
      error.hidden = false;
      return;
    }
    try {
      await busy($("conciliation-confirm"), () =>
        resolveMovement(mode, candidateId, justification),
      );
      dialog.close();
    } catch (caught) {
      error.textContent = caught.message;
      error.hidden = false;
    }
  });

  return { hide, reset, show };
}
