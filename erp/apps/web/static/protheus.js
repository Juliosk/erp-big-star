// Espelha empresa e conexão na barra de status. Não altera nenhum fluxo do app.
const $ = (id) => document.getElementById(id);
const company = $("company");
const conn = $("connection-status");
const out = { company: $("sb-company"), conn: $("sb-conn"), date: $("sb-date") };
function sync() {
  const opt = company?.selectedOptions?.[0];
  if (out.company) out.company.textContent = opt && opt.value ? opt.textContent : "—";
  if (out.conn && conn) out.conn.textContent = conn.textContent;
}
if (out.date) out.date.textContent = new Date().toLocaleDateString("pt-BR");
if (company) company.addEventListener("change", sync);
if (conn) new MutationObserver(sync).observe(conn, { childList: true, characterData: true, subtree: true });
if (company) new MutationObserver(sync).observe(company, { childList: true });
sync();

// ---- Padrão browse: seleção de linha, Visualizar/Alterar e busca na página ----
const rows = $("product-rows");
const bView = $("px-view");
const bEdit = $("px-edit");
const find = $("px-find");
let selected = null;
function select(tr) {
  if (selected) selected.classList.remove("px-sel");
  selected = tr && tr.isConnected ? tr : null;
  if (selected) selected.classList.add("px-sel");
  if (bView) bView.disabled = !selected;
  if (bEdit) bEdit.disabled = !selected;
}
function openSelected() {
  selected?.querySelector("button")?.click();
}
if (rows) {
  rows.addEventListener("click", (e) => {
    const tr = e.target.closest("tr");
    if (tr && !e.target.closest("button")) select(tr);
  });
  rows.addEventListener("dblclick", (e) => {
    const tr = e.target.closest("tr");
    if (tr) {
      select(tr);
      openSelected();
    }
  });
  rows.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.closest("tr") === e.target) {
      select(e.target);
      openSelected();
    }
  });
  function applyFind() {
    const q = (find?.value || "").trim().toLowerCase();
    for (const tr of rows.children) {
      tr.hidden = q !== "" && !tr.textContent.toLowerCase().includes(q);
    }
    if (selected?.hidden) select(null);
  }
  new MutationObserver(() => {
    for (const tr of rows.children) tr.tabIndex = 0;
    select(null);
    applyFind();
  }).observe(rows, { childList: true });
  find?.addEventListener("input", applyFind);
}
bView?.addEventListener("click", openSelected);
bEdit?.addEventListener("click", openSelected);

// ---- Pastas no detalhe: transforma os painéis em abas ----
const cols = document.querySelector("#detail .detail-columns");
if (cols && cols.children.length > 1) {
  cols.classList.add("px-tabbed");
  const panels = [...cols.children];
  const tabs = [
    { label: "Visão geral", panel: null },
    ...panels.map((panel) => ({
      label: panel.querySelector("h2")?.textContent || "Pasta",
      panel,
    })),
  ];
  const bar = document.createElement("div");
  bar.className = "px-tabs";
  bar.setAttribute("role", "tablist");
  const show = (n) => {
    const activePanel = tabs[n].panel;
    panels.forEach((panel) => (panel.hidden = activePanel !== null && panel !== activePanel));
    [...bar.children].forEach((b, i) => b.setAttribute("aria-selected", String(i === n)));
  };
  tabs.forEach((tab, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "secondary";
    b.setAttribute("role", "tab");
    b.textContent = tab.label;
    b.addEventListener("click", () => show(i));
    bar.append(b);
  });
  cols.before(bar);
  show(0);
}

// ---- Vendas em pastas (Cotações / Pedidos de venda / Liberação de estoque) ----
let setSalesTab = () => {};
{
  const grid = document.querySelector("#sales .sales-grid");
  const pQuotes = grid?.querySelector(".sales-quotes");
  const pDetail = grid?.querySelector(".sales-detail");
  const pOrders = grid?.querySelector(".sales-orders");
  const pRes = document.getElementById("sales-reservation-panel");
  if (grid && pQuotes && pDetail && pOrders && pRes) {
    const TABS = [
      ["all", "Visão geral", [pQuotes, pDetail, pOrders, pRes]],
      ["quotes", "Cotações", [pQuotes, pDetail]],
      ["orders", "Pedidos de venda", [pOrders]],
      // A liberação mantém a fila de pedidos visível para permitir a troca de
      // ordem sem retornar manualmente à pasta anterior.
      ["res", "Liberação de estoque", [pOrders, pRes]],
    ];
    // A visão geral preserva o fluxo vertical legado. Os atalhos virtuais
    // direcionam explicitamente para as pastas especializadas.
    let active = "all";
    const bar = document.createElement("div");
    bar.className = "px-tabs";
    bar.setAttribute("role", "tablist");
    const hint = document.createElement("p");
    hint.className = "hint px-res-hint";
    hint.textContent = "Selecione um pedido na pasta “Pedidos de venda” para liberar o estoque.";
    const draw = () => {
      const visible = new Set(TABS.find(([key]) => key === active)?.[2] || []);
      for (const panel of [pQuotes, pDetail, pOrders, pRes]) panel.classList.toggle("px-off", !visible.has(panel));
      [...bar.children].forEach((b, i) => b.setAttribute("aria-selected", String(TABS[i][0] === active)));
      hint.hidden = !(active === "res" && pRes.hidden);
    };
    TABS.forEach(([key, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "secondary";
      b.setAttribute("role", "tab");
      b.textContent = label;
      b.addEventListener("click", () => { active = key; draw(); });
      bar.append(b);
    });
    grid.classList.add("px-tabbed");
    grid.before(bar, hint);
    setSalesTab = (key) => { active = key; draw(); };
    document.getElementById("sales-nav")?.addEventListener("click", () => {
      active = "all";
      draw();
    });
    company?.addEventListener("change", () => {
      active = "all";
      draw();
    });
    // quando um pedido é selecionado (painel de reserva aparece), abre a pasta de liberação
    new MutationObserver(() => {
      if (!pRes.hidden) active = "res";
      else if (active === "res") active = "all";
      draw();
    }).observe(pRes, { attributes: true, attributeFilter: ["hidden"] });
    draw();
  }
}

// ---- Menu em grupos (árvore) ----
const nav = document.querySelector(".sidebar nav");
if (nav) {
  const GROUPS = [
    ["Cadastros", ["M2", "M14"]],
    ["Faturamento", []],
    ["Governança de dados", ["M23"]],
    ["Estoque / Expedição", ["M5", "M9", "M10"]],
    ["Comercial", ["M15", "M22"]],
    ["Compras", ["M6"]],
    ["Produção", ["M7"]],
    ["Fiscal", ["M11"]],
    ["Financeiro", ["M12"]],
  ];
  const links = [...nav.querySelectorAll("a")];
  const codeOf = (a) => a.querySelector("span")?.textContent.trim() || "";
  const byId = (id) => document.getElementById(id);

  // Janelas abertas (abas no topo, como no Protheus)
  const wins = [];
  let activeWin = null;
  const winBar = document.createElement("div");
  winBar.className = "px-windows";
  winBar.setAttribute("role", "tablist");
  winBar.setAttribute("aria-label", "Janelas abertas");
  winBar.hidden = true;
  document.querySelector(".topbar")?.after(winBar);
  const labelOf = (a) =>
    [...a.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim() || a.textContent.trim();
  function drawWins() {
    winBar.replaceChildren();
    for (const w of wins) {
      const t = document.createElement("div");
      t.className = "px-wtab";
      t.setAttribute("role", "tab");
      t.setAttribute("aria-selected", String(w === activeWin));
      const l = document.createElement("button");
      l.type = "button";
      l.className = "px-wlabel";
      l.textContent = labelOf(w.el);
      l.addEventListener("click", () => { if (w !== activeWin) w.el.click(); });
      t.append(l);
      if (wins.length > 1) {
        const x = document.createElement("button");
        x.type = "button";
        x.className = "px-wclose";
        x.textContent = "×";
        x.setAttribute("aria-label", `Fechar ${labelOf(w.el)}`);
        x.addEventListener("click", (e) => { e.stopPropagation(); closeWin(w); });
        t.append(x);
      }
      winBar.append(t);
    }
    winBar.hidden = wins.length === 0;
  }
  function openWin(el) {
    let w = wins.find((x) => x.el === el);
    if (!w) { w = { el }; wins.push(w); }
    activeWin = w;
    drawWins();
  }
  function closeWin(w) {
    const i = wins.indexOf(w);
    if (i < 0) return;
    wins.splice(i, 1);
    if (w === activeWin) {
      const next = wins[i] || wins[i - 1] || null;
      activeWin = next;
      drawWins();
      next?.el.click();
    } else drawWins();
  }
  function pruneWins() {
    const keep = wins.filter((w) => !w.el.hidden);
    if (keep.length === wins.length) return;
    wins.length = 0;
    wins.push(...keep);
    if (!wins.some((w) => w === activeWin)) activeWin = null;
    drawWins();
  }

  // Itens virtuais do grupo Faturamento: reaproveitam as telas de Vendas e Fiscal
  const virtuals = [];
  let viaVirtual = false;
  function clearVirtualCurrent() {
    for (const v of virtuals) if (v.el.hasAttribute("aria-current")) v.el.removeAttribute("aria-current");
  }
  function addVirtual(label, code, realId, go, opts = {}) {
    const el = document.createElement("a");
    el.href = realId ? `#${realId.replace(/-nav$/, "")}` : "#";
    el.dataset.pxVirtual = "1";
    el.dataset.pxGroup = opts.group || "Faturamento";
    el.innerHTML = `${label} <span>${code}</span>`;
    if (!realId) {
      el.classList.add("px-soon");
      el.setAttribute("aria-disabled", "true");
      el.title = "Em desenvolvimento: depende do limite de crédito por cliente (backend).";
    }
    el.addEventListener("click", (e) => {
      e.preventDefault();
      if (!realId) return;
      viaVirtual = true;
      setTimeout(() => { viaVirtual = false; }, 0);
      if (!opts.direct) byId(realId)?.click();
      go?.();
      clearVirtualCurrent();
      el.setAttribute("aria-current", "page");
      openWin(el);
    });
    virtuals.push({ el, realId: realId || "sales-nav" });
    links.push(el);
  }
  addVirtual("Grupos de clientes", "M14", "customers-nav", () => byId("customers-groups-button")?.click(), { direct: true, group: "Cadastros" });
  addVirtual("Pedido de Venda", "M15", "sales-nav", () => setSalesTab("orders"));
  addVirtual("Liberação de Estoque", "M5", "sales-nav", () => setSalesTab("res"));
  addVirtual("Liberação de Crédito", "em breve", null);
  addVirtual("Nota Fiscal de Saída", "M11", "fiscal-nav", () => byId("fiscal-outbound-tab")?.click());

  const groups = [];
  const make = (name) => {
    const g = document.createElement("div");
    // Os grupos iniciam expandidos para manter os links oficiais imediatamente
    // navegáveis. O usuário ainda pode recolhê-los pelo cabeçalho da árvore.
    g.className = "px-group open";
    const h = document.createElement("button");
    h.type = "button";
    h.className = "px-ghead";
    h.textContent = name;
    h.setAttribute("aria-expanded", "true");
    const body = document.createElement("div");
    body.className = "px-gbody";
    g.append(h, body);
    h.addEventListener("click", () => {
      g.classList.toggle("open");
      h.setAttribute("aria-expanded", String(g.classList.contains("open")));
    });
    groups.push({ g, h, body });
    return { g, body };
  };
  const byName = new Map();
  const slot = (name) => byName.get(name) || (byName.set(name, make(name)), byName.get(name));
  for (const [name] of GROUPS) slot(name);
  for (const a of links) {
    const found = GROUPS.find(([, codes]) => codes.includes(codeOf(a)));
    slot(a.dataset.pxGroup || (found ? found[0] : "Outros")).body.append(a);
  }
  const find = document.createElement("div");
  find.className = "px-menu-find";
  find.innerHTML = '<input id="px-menu-find" type="search" placeholder="Buscar programa… (F3)" aria-label="Buscar programa" autocomplete="off">';
  nav.prepend(find);
  nav.append(...groups.map((x) => x.g));
  const q = () => find.querySelector("input");
  function syncVirtual() {
    for (const { el, realId } of virtuals) {
      const h = byId(realId)?.hidden ?? true;
      if (el.hidden !== h) el.hidden = h;
    }
  }
  function refresh() {
    const term = q().value.trim().toLowerCase();
    for (const a of links) a.classList.toggle("px-nomatch", term !== "" && !a.textContent.toLowerCase().includes(term));
    for (const { g, h, body } of groups) {
      const vis = [...body.children].filter((a) => !a.hidden && !a.classList.contains("px-nomatch"));
      const hide = vis.length === 0;
      if (g.hidden !== hide) g.hidden = hide; // só altera se mudou (evita laço do observer)
      const current = [...body.children].some((a) => a.getAttribute("aria-current") === "page");
      if (term !== "" && vis.length) g.classList.add("open");
      if (current) g.classList.add("open");
      h.setAttribute("aria-expanded", String(g.classList.contains("open")));
    }
  }
  new MutationObserver((records) => {
    // reage só aos links (permissão / página atual); ignora mudanças feitas pelos próprios grupos
    if (!records.some((r) => r.target.tagName === "A")) return;
    const wentElsewhere = records.some(
      (r) => r.attributeName === "aria-current" && r.target.getAttribute("aria-current") === "page" && !r.target.dataset.pxVirtual,
    );
    if (wentElsewhere && !viaVirtual) {
      clearVirtualCurrent();
      const r = records.find(
        (x) => x.attributeName === "aria-current" && x.target.getAttribute("aria-current") === "page" && !x.target.dataset.pxVirtual,
      );
      if (r) openWin(r.target);
    }
    syncVirtual();
    pruneWins();
    refresh();
  }).observe(nav, { subtree: true, attributes: true, attributeFilter: ["hidden", "aria-current"] });
  q().addEventListener("input", refresh);
  document.addEventListener("keydown", (e) => {
    if (e.key === "F3") {
      e.preventDefault();
      q().focus();
    }
  });
  syncVirtual();
  refresh();
}

// ---- Tema: Automático / Claro / Escuro ----
const THEMES = ["auto", "light", "dark"];
const LABEL = { auto: "Automático", light: "Claro", dark: "Escuro" };
let pref = "auto";
try {
  const s = localStorage.getItem("px-theme");
  if (THEMES.includes(s)) pref = s;
} catch { /* armazenamento indisponível: segue automático */ }
const mq = window.matchMedia("(prefers-color-scheme: dark)");
const themeBtn = document.createElement("button");
themeBtn.id = "px-theme";
themeBtn.type = "button";
themeBtn.className = "quiet";
function applyTheme() {
  const dark = pref === "dark" || (pref === "auto" && mq.matches);
  document.documentElement.dataset.pxTheme = dark ? "dark" : "light";
  themeBtn.textContent = `Tema: ${LABEL[pref]}`;
}
themeBtn.addEventListener("click", () => {
  pref = THEMES[(THEMES.indexOf(pref) + 1) % THEMES.length];
  try { localStorage.setItem("px-theme", pref); } catch { /* ignora */ }
  applyTheme();
});
mq.addEventListener?.("change", applyTheme);
document.querySelector(".topbar > div")?.prepend(themeBtn);
applyTheme();
