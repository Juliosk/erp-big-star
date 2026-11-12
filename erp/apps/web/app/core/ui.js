// Utilitários de interface (sem innerHTML: tudo entra como texto).
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in el) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...kids.flat(Infinity).filter((c) => c != null && c !== false));
  return el;
}

export const money = (v, currency = "BRL") =>
  Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency });
export const qty = (v) => Number(v || 0).toLocaleString("pt-BR", { maximumFractionDigits: 6 });
export const shortId = (id) => String(id || "").slice(0, 8);

export const LABELS = {
  DRAFT: "Rascunho", SENT: "Enviada", ACCEPTED: "Aceita", PARTIALLY_ACCEPTED: "Aceita parcialmente",
  LOST: "Perdida", CONVERTED: "Convertida", APPROVED: "Aprovado", CANCELLED: "Cancelado",
  COMPLETED: "Concluído", HELD: "Reserva ativa", RELEASED: "Liberada", EXPIRED: "Expirada",
};
export const badge = (status) => h("span", { class: `badge s-${status}` }, LABELS[status] || status);

export const field = (label, value, wide = "") =>
  h("div", { class: `field ${wide}` }, h("span", { class: "field-label" }, label), h("div", { class: "field-value" }, value ?? "—"));

export function toast(message, kind = "info") {
  const box = document.getElementById("toasts");
  const node = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  box.append(node);
  setTimeout(() => node.remove(), kind === "error" ? 9000 : 5000);
}

// Janela modal com barra de título, pastas (abas) opcionais e botões.
export function openDialog({ title, subtitle, folders = [], body, actions = [{ label: "Fechar" }] }) {
  const dlg = h("dialog", { class: "win" });
  const close = () => dlg.close();
  const head = h("div", { class: "win-head" },
    h("strong", {}, title), subtitle ? h("span", { class: "win-sub" }, subtitle) : null,
    h("button", { type: "button", class: "win-x", "aria-label": "Fechar", onclick: close }, "✕"));
  const content = h("div", { class: "win-body" });
  if (folders.length) {
    const bar = h("div", { class: "folders", role: "tablist" });
    const panes = folders.map((f, i) => {
      const pane = h("div", { class: "folder-pane", hidden: i !== 0 }, f.content);
      const b = h("button", { type: "button", role: "tab", "aria-selected": String(i === 0), onclick: () => {
        [...bar.children].forEach((x, j) => x.setAttribute("aria-selected", String(i === j)));
        panes.forEach((p, j) => { p.hidden = i !== j; });
      } }, f.label);
      bar.append(b);
      return pane;
    });
    content.append(bar, ...panes);
  }
  if (body) content.append(body);
  const foot = h("div", { class: "win-foot" }, actions.map((a) =>
    h("button", { type: "button", class: `btn${a.primary ? " primary" : ""}`, onclick: async () => {
      if (a.onClick) { const keep = await a.onClick(close); if (keep === false) return; }
      if (!a.keepOpen) close();
    } }, a.label)));
  dlg.append(head, content, foot);
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return { dlg, close };
}

export function confirmBox(title, message, okLabel = "Confirmar") {
  return new Promise((resolve) => {
    let answered = false;
    const done = (v) => { answered = true; resolve(v); };
    const { dlg } = openDialog({ title, body: h("p", { class: "confirm-text" }, message), actions: [
      { label: "Cancelar", onClick: () => done(false) },
      { label: okLabel, primary: true, onClick: () => done(true) },
    ] });
    dlg.addEventListener("close", () => { if (!answered) resolve(false); });
  });
}
