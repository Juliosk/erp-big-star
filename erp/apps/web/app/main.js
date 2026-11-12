import { session } from "./core/session.js";
import { setUnauthorizedHandler } from "./core/api.js";
import { h, toast } from "./core/ui.js";
import { windows } from "./core/windows.js";
import { MODULES } from "./modules/registry.js";

const $ = (id) => document.getElementById(id);

// ---- Tema: Automático / Claro / Escuro ----
const THEMES = ["auto", "light", "dark"];
const THEME_LABEL = { auto: "Automático", light: "Claro", dark: "Escuro" };
let pref = "auto";
try { const s = localStorage.getItem("erp-theme"); if (THEMES.includes(s)) pref = s; } catch { /* segue automático */ }
const mq = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  document.documentElement.dataset.theme = pref === "dark" || (pref === "auto" && mq.matches) ? "dark" : "light";
  $("theme").textContent = `Tema: ${THEME_LABEL[pref]}`;
}
$("theme").addEventListener("click", () => {
  pref = THEMES[(THEMES.indexOf(pref) + 1) % THEMES.length];
  try { localStorage.setItem("erp-theme", pref); } catch { /* ignora */ }
  applyTheme();
});
mq.addEventListener?.("change", applyTheme);
applyTheme();

// ---- Menu em grupos ----
const menu = $("menu-groups");
const items = new Map();
function buildMenu() {
  menu.replaceChildren();
  items.clear();
  const groups = [...new Set(MODULES.map((m) => m.group))];
  for (const name of groups) {
    const list = h("div", { class: "g-body" });
    const head = h("button", { type: "button", class: "g-head", "aria-expanded": "true" }, name);
    const group = h("div", { class: "group open" }, head, list);
    head.addEventListener("click", () => {
      group.classList.toggle("open");
      head.setAttribute("aria-expanded", String(group.classList.contains("open")));
    });
    for (const def of MODULES.filter((m) => m.group === name)) {
      if (def.permission && !session.can(def.permission)) continue;
      const item = h("button", { type: "button", class: "m-item", disabled: Boolean(def.soon),
        title: def.soon ? "Ainda não migrada para o novo front. Use o sistema anterior." : "",
        onclick: () => windows.open(def) }, def.title, h("span", { class: "code" }, def.soon ? "em breve" : def.code));
      items.set(def.id, { item, group });
      list.append(item);
    }
    if (list.children.length) menu.append(group);
  }
}
function markActive() {
  const activeId = windows.active?.def.id;
  for (const [id, { item }] of items) item.setAttribute("aria-current", id === activeId ? "page" : "false");
  const def = windows.active?.def;
  $("crumb").textContent = def ? `${def.group} / ${def.title}` : "Início";
}
windows.onChange = markActive;
$("menu-find").addEventListener("input", (e) => {
  const term = e.target.value.trim().toLowerCase();
  for (const [id, { item, group }] of items) {
    const match = !term || item.textContent.toLowerCase().includes(term);
    item.hidden = !match;
    if (term && match) group.classList.add("open");
  }
  for (const g of menu.children) g.hidden = ![...g.querySelectorAll(".m-item")].some((i) => !i.hidden);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "F3" && session.connected) { e.preventDefault(); $("menu-find").focus(); }
});

// ---- Sessão ----
function showShell() {
  $("login").hidden = true;
  $("shell").hidden = false;
  $("dev-banner").hidden = !session.devAuth;
  $("status-session").textContent = session.devAuth ? "Conectado · desenvolvimento" : "Conectado";
  $("company").replaceChildren(...session.companies.map((c) => h("option", { value: c.id }, c.trade_name || c.legal_name)));
  $("company").disabled = !session.companies.length;
  $("status-company").textContent = session.companyName;
  buildMenu();
  windows.init($("windows"), $("stage"));
  const first = MODULES.find((m) => !m.soon && (!m.permission || session.can(m.permission)));
  if (first) windows.open(first);
  else markActive();
}
function showLogin(message = "") {
  windows.closeAll();
  $("shell").hidden = true;
  $("login").hidden = false;
  $("login-error").textContent = message;
  $("token").value = "";
  $("token").focus();
}
setUnauthorizedHandler(() => {
  if (!session.connected) return;
  session.disconnect();
  showLogin("Sessão expirada. Conecte-se novamente.");
});
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const token = $("token").value.trim();
  if (!token) { $("login-error").textContent = "Informe o token de acesso."; return; }
  $("login-error").textContent = "";
  $("connect").disabled = true;
  try {
    await session.connect(token);
    $("token").value = "";
    showShell();
  } catch (error) {
    $("login-error").textContent = error.message;
  } finally {
    $("connect").disabled = false;
  }
});
$("company").addEventListener("change", (e) => {
  session.company = e.target.value;
  $("status-company").textContent = session.companyName;
  windows.refreshAll();
});
$("logout").addEventListener("click", () => { session.disconnect(); showLogin(); });
$("db").textContent = new Date().toLocaleDateString("pt-BR");
$("token").focus();
