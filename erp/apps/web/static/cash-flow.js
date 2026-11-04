const $ = (id) => document.getElementById(id);
const svg = (name) => document.createElementNS("http://www.w3.org/2000/svg", name);

const horizonLabels = {
  SHORT_TERM: "Curto prazo",
  MEDIUM_TERM: "Médio prazo",
  LONG_TERM: "Longo prazo",
};
const alertLabels = {
  CASH_RUPTURE: "Ruptura de caixa",
  SAFETY_THRESHOLD: "Reserva de segurança",
  DATE_CONCENTRATION: "Concentração por data",
  CATEGORY_CONCENTRATION: "Concentração por categoria",
  EXPOSURE_CONCENTRATION: "Dependência concentrada",
  DAILY_OUTLIER: "Pico fora do padrão",
  SCENARIO_SENSITIVITY: "Sensibilidade do cenário",
};

export function mountCashFlow({ api, context, notice, enter }) {
  let horizon = "SHORT_TERM";
  let projection = null;
  let showingScenario = false;

  const can = (permission) => context().permissions.has(permission);
  const money = (value, currency = "BRL") =>
    new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(Number(value || 0));
  const shortDate = (value) =>
    new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" }).format(
      new Date(`${value}T12:00:00`),
    );

  function hide() {
    $("cash-flow").hidden = true;
    $("cash-flow-nav").removeAttribute("aria-current");
    $("cash-flow-scenario-dialog").close();
  }

  function reset() {
    hide();
    horizon = "SHORT_TERM";
    projection = null;
    showingScenario = false;
    $("cash-flow-alert-list").replaceChildren();
    $("cash-flow-chart").replaceChildren();
  }

  function setBusy(button, busy, label) {
    button.disabled = busy;
    button.dataset.label ||= button.textContent;
    button.textContent = busy ? label : button.dataset.label;
  }

  function renderEmpty() {
    $("cash-flow-empty").hidden = false;
    $("cash-flow-content").hidden = true;
    $("cash-flow-alert-list").replaceChildren();
    $("cash-flow-alert-empty").hidden = false;
  }

  function renderMetrics(value) {
    const summary = value.summary;
    const currency = summary.currency;
    $("cash-flow-opening").textContent = money(summary.opening_balance, currency);
    $("cash-flow-operational-close").textContent = money(
      summary.operational_closing_balance,
      currency,
    );
    $("cash-flow-scenario-close").textContent = money(
      summary.scenario_closing_balance,
      currency,
    );
    $("cash-flow-reserve").textContent = money(value.minimum_reserve.amount, currency);
    $("cash-flow-version").textContent = `ETag · v${value.version}`;
    $("cash-flow-period").textContent =
      `${shortDate(value.horizon_start)} — ${shortDate(value.horizon_end)}`;
    $("cash-flow-calculated").textContent = new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value.calculated_at));
    $("cash-flow-state").textContent =
      value.summary.liquidity_state === "INCOMPLETE" ? "Dados incompletos" : "Posição calculada";
    $("cash-flow-state").className = `cash-flow-state ${value.summary.liquidity_state}`;
    $("cash-flow-gap").hidden = value.source_gaps.length === 0;
    $("cash-flow-gap-text").textContent = value.source_gaps.length
      ? `${value.source_gaps.length} fonte(s) ainda sem cobertura. O ERP não estimou recebíveis ausentes.`
      : "";
    $("cash-flow-scenario-mark").hidden = !showingScenario;
  }

  function plot(value) {
    const buckets = value.buckets;
    const host = $("cash-flow-chart");
    host.replaceChildren();
    if (!buckets.length) return;
    const width = 920;
    const height = 300;
    const pad = { left: 72, right: 24, top: 28, bottom: 48 };
    const reserve = Number(value.minimum_reserve.amount);
    const operational = buckets.map((item) => Number(item.operational_closing_balance.amount));
    const scenario = buckets.map((item) => Number(item.scenario_closing_balance.amount));
    const values = [0, reserve, ...operational, ...scenario];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(max - min, 1);
    const x = (index) =>
      pad.left + (index * (width - pad.left - pad.right)) / Math.max(buckets.length - 1, 1);
    const y = (amount) => pad.top + ((max - amount) * (height - pad.top - pad.bottom)) / span;
    const root = svg("svg");
    root.setAttribute("viewBox", `0 0 ${width} ${height}`);
    root.setAttribute("role", "img");
    root.setAttribute(
      "aria-label",
      `Evolução de liquidez de ${shortDate(value.horizon_start)} a ${shortDate(value.horizon_end)}`,
    );

    const danger = svg("rect");
    danger.setAttribute("x", pad.left);
    danger.setAttribute("y", y(reserve));
    danger.setAttribute("width", width - pad.left - pad.right);
    danger.setAttribute("height", Math.max(height - pad.bottom - y(reserve), 0));
    danger.setAttribute("class", "cash-flow-danger-zone");
    root.append(danger);

    [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
      const amount = min + span * ratio;
      const line = svg("line");
      line.setAttribute("x1", pad.left);
      line.setAttribute("x2", width - pad.right);
      line.setAttribute("y1", y(amount));
      line.setAttribute("y2", y(amount));
      line.setAttribute("class", "cash-flow-grid-line");
      const label = svg("text");
      label.setAttribute("x", pad.left - 10);
      label.setAttribute("y", y(amount) + 4);
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "cash-flow-axis-label");
      label.textContent = new Intl.NumberFormat("pt-BR", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(amount);
      root.append(line, label);
    });

    const reserveLine = svg("line");
    reserveLine.setAttribute("x1", pad.left);
    reserveLine.setAttribute("x2", width - pad.right);
    reserveLine.setAttribute("y1", y(reserve));
    reserveLine.setAttribute("y2", y(reserve));
    reserveLine.setAttribute("class", "cash-flow-reserve-line");
    root.append(reserveLine);

    function drawLine(points, className) {
      const path = svg("path");
      path.setAttribute(
        "d",
        points.map((amount, index) => `${index ? "L" : "M"}${x(index)},${y(amount)}`).join(" "),
      );
      path.setAttribute("class", className);
      root.append(path);
      points.forEach((amount, index) => {
        if (amount >= reserve) return;
        const point = svg("circle");
        point.setAttribute("cx", x(index));
        point.setAttribute("cy", y(amount));
        point.setAttribute("r", 5);
        point.setAttribute("class", "cash-flow-breach-point");
        root.append(point);
      });
    }
    drawLine(operational, "cash-flow-line operational");
    drawLine(scenario, "cash-flow-line scenario");

    const labelIndexes = [...new Set([0, Math.floor((buckets.length - 1) / 2), buckets.length - 1])];
    labelIndexes.forEach((index) => {
      const label = svg("text");
      label.setAttribute("x", x(index));
      label.setAttribute("y", height - 18);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "cash-flow-axis-label");
      label.textContent = shortDate(buckets[index].end_on);
      root.append(label);
    });
    host.append(root);
  }

  function renderMix(value) {
    const summary = value.summary;
    const currency = summary.currency;
    const rows = [
      ["Realizado", summary.realized_inflows, summary.realized_outflows],
      ["Comprometido", summary.committed_inflows, summary.committed_outflows],
      ["Cenário", summary.scenario_inflows, summary.scenario_outflows],
    ];
    $("cash-flow-mix").replaceChildren(
      ...rows.map(([label, inflow, outflow]) => {
        const row = document.createElement("div");
        const name = document.createElement("strong");
        const incoming = document.createElement("span");
        const outgoing = document.createElement("span");
        name.textContent = label;
        incoming.textContent = `+ ${money(inflow, currency)}`;
        outgoing.textContent = `− ${money(outflow, currency)}`;
        row.append(name, incoming, outgoing);
        return row;
      }),
    );
  }

  function renderAlerts(result) {
    $("cash-flow-alert-count").textContent = String(result.data.length);
    $("cash-flow-alert-empty").hidden = result.data.length > 0;
    $("cash-flow-alert-list").replaceChildren(
      ...result.data.map((alert) => {
        const article = document.createElement("article");
        article.className = `cash-flow-alert ${alert.severity}`;
        const marker = document.createElement("span");
        const content = document.createElement("div");
        const title = document.createElement("strong");
        const meta = document.createElement("small");
        const values = document.createElement("p");
        marker.textContent = alert.severity === "CRITICAL" ? "!" : "△";
        title.textContent = alertLabels[alert.alert_type] || alert.alert_type;
        meta.textContent = `${alert.source === "SCENARIO" ? "Simulação" : "Projeção"} · ${alert.breach_on ? shortDate(alert.breach_on) : "horizonte"}`;
        values.textContent =
          `${money(alert.actual_value, alert.currency)} · limite ${money(alert.threshold_value, alert.currency)}`;
        content.append(title, meta, values);
        article.append(marker, content);
        return article;
      }),
    );
  }

  async function loadAlerts() {
    if (!projection) return;
    const result = await api(
      `finance/cash-flow/alerts?company_id=${context().company}&projection_id=${projection.id}&page_size=50`,
    );
    renderAlerts(result);
  }

  function render(value, { scenario = false } = {}) {
    projection = value;
    showingScenario = scenario;
    $("cash-flow-empty").hidden = true;
    $("cash-flow-content").hidden = false;
    renderMetrics(value);
    plot(value);
    renderMix(value);
    $("cash-flow-simulate").hidden = !can("finance.cash_flow.scenario");
    $("cash-flow-recalculate").hidden = !can("finance.cash_flow.project") || scenario;
    $("cash-flow-reset-scenario").hidden = !scenario;
  }

  async function load() {
    const result = await api(
      `finance/cash-flow/horizons/${horizon}?company_id=${context().company}&page_size=20`,
    );
    const latest = result.data[0];
    if (!latest) {
      projection = null;
      renderEmpty();
      return;
    }
    render(latest);
    await loadAlerts();
  }

  async function show() {
    if (!can("finance.cash_flow.read")) return;
    enter();
    history.replaceState({}, "", "/ui/finance/cash-flow");
    $("cash-flow").hidden = false;
    await load();
  }

  $("cash-flow-refresh").addEventListener("click", () =>
    load().catch((error) => notice(error.message)),
  );
  document.querySelectorAll("[data-cash-flow-horizon]").forEach((button) => {
    button.addEventListener("click", () => {
      horizon = button.dataset.cashFlowHorizon;
      document.querySelectorAll("[data-cash-flow-horizon]").forEach((item) =>
        item.setAttribute("aria-pressed", String(item === button)),
      );
      $("cash-flow-horizon-label").textContent = horizonLabels[horizon];
      load().catch((error) => notice(error.message));
    });
  });
  $("cash-flow-recalculate").addEventListener("click", async (event) => {
    if (!projection) return;
    const button = event.currentTarget;
    setBusy(button, true, "Recalculando…");
    try {
      const result = await api(
        `finance/cash-flow/projections/${projection.id}/recalculate?company_id=${context().company}`,
        {
          method: "POST",
          version: projection.version,
          key: crypto.randomUUID(),
        },
      );
      render(result.projection);
      await loadAlerts();
      notice("Posição de caixa recalculada e alertas reavaliados.");
    } finally {
      setBusy(button, false, "");
    }
  });
  $("cash-flow-simulate").addEventListener("click", () => {
    if (!projection) return;
    $("cash-flow-scenario-form").reset();
    $("cash-flow-scenario-dialog").showModal();
  });
  $("cash-flow-scenario-close").addEventListener("click", () =>
    $("cash-flow-scenario-dialog").close(),
  );
  $("cash-flow-scenario-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!projection) return;
    const button = event.submitter;
    setBusy(button, true, "Simulando…");
    try {
      const result = await api("finance/cash-flow/scenarios", {
        method: "POST",
        version: projection.version,
        key: crypto.randomUUID(),
        body: {
          company_id: context().company,
          projection_id: projection.id,
          scenario: {
            id: crypto.randomUUID(),
            name: $("cash-flow-scenario-name").value,
            receivable_delay_days: Number($("cash-flow-delay").value),
            cost_variation_rate: (Number($("cash-flow-cost-variation").value) / 100).toFixed(4),
            business_day_convention: "FOLLOWING",
          },
        },
      });
      render(result.projection, { scenario: true });
      await loadAlerts();
      $("cash-flow-scenario-dialog").close();
      notice("Cenário calculado sem alterar a posição operacional.");
    } finally {
      setBusy(button, false, "");
    }
  });
  $("cash-flow-reset-scenario").addEventListener("click", async () => {
    try {
      await load();
      notice("Posição operacional restaurada.");
    } catch (error) {
      notice(error.message);
    }
  });

  return { hide, reset, show };
}
