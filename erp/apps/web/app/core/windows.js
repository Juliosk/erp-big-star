// Janelas abertas (abas no topo), no estilo Protheus.
import { h } from "./ui.js";

export const windows = {
  list: [],
  active: null,
  onChange: () => {},
  init(bar, stage) { this.bar = bar; this.stage = stage; this.draw(); },
  open(def) {
    let w = this.list.find((x) => x.def.id === def.id);
    if (!w) {
      const pane = h("section", { class: "pane", hidden: true });
      this.stage.append(pane);
      w = { def, pane, instance: null };
      this.list.push(w);
      w.instance = def.mount(pane) || {};
    }
    this.activate(w);
  },
  activate(w) {
    this.active = w;
    for (const x of this.list) x.pane.hidden = x !== w;
    w.instance?.activated?.();
    this.draw();
    this.onChange();
  },
  close(w) {
    const i = this.list.indexOf(w);
    if (i < 0) return;
    w.instance?.destroy?.();
    w.pane.remove();
    this.list.splice(i, 1);
    if (this.active === w) {
      const next = this.list[i] || this.list[i - 1] || null;
      this.active = null;
      if (next) return this.activate(next);
    }
    this.draw();
    this.onChange();
  },
  closeAll() {
    [...this.list].forEach((w) => { w.instance?.destroy?.(); w.pane.remove(); });
    this.list = [];
    this.active = null;
    this.draw();
    this.onChange();
  },
  refreshAll() { this.list.forEach((w) => w.instance?.refresh?.()); },
  draw() {
    if (!this.bar) return;
    this.bar.replaceChildren(...this.list.map((w) =>
      h("div", { class: "wtab", role: "tab", "aria-selected": String(w === this.active) },
        h("button", { type: "button", class: "wlabel", onclick: () => this.activate(w) }, w.def.title),
        h("button", { type: "button", class: "wclose", "aria-label": `Fechar ${w.def.title}`, onclick: (e) => { e.stopPropagation(); this.close(w); } }, "×"))));
    this.bar.hidden = this.list.length === 0;
    const welcome = document.getElementById("welcome");
    if (welcome) welcome.hidden = this.list.length > 0;
  },
};
