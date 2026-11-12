// Grid de browse: seleção de linha, ordenação por coluna, Enter/duplo clique abre.
import { h } from "./ui.js";

export function createGrid({ columns, getKey, onSelect = () => {}, onOpen = () => {}, empty = "Nenhum registro." }) {
  let rows = [];
  let selected = null;
  let sort = { index: -1, dir: 1 };
  const tbody = h("tbody");
  const head = h("tr", {}, columns.map((c, i) =>
    h("th", { class: c.align === "right" ? "num" : "", tabIndex: 0, "aria-sort": "none", onclick: () => toggle(i),
      onkeydown: (e) => { if (e.key === "Enter") toggle(i); } }, c.label)));
  const emptyMsg = h("p", { class: "grid-empty" }, empty);
  const el = h("div", { class: "grid" }, h("table", {}, h("thead", {}, head), tbody), emptyMsg);

  const value = (c, r) => (c.sortValue ? c.sortValue(r) : r[c.key]);
  function toggle(i) {
    sort = { index: i, dir: sort.index === i ? -sort.dir : 1 };
    [...head.children].forEach((th, j) => th.setAttribute("aria-sort", j === i ? (sort.dir === 1 ? "ascending" : "descending") : "none"));
    draw();
  }
  function ordered() {
    if (sort.index < 0) return rows;
    const c = columns[sort.index];
    return [...rows].sort((a, b) => {
      const x = value(c, a), y = value(c, b);
      const r = typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""), "pt-BR", { numeric: true });
      return r * sort.dir;
    });
  }
  function select(row) {
    selected = row;
    draw();
    onSelect(row);
  }
  function draw() {
    const list = ordered();
    emptyMsg.hidden = list.length > 0;
    tbody.replaceChildren(...list.map((row) => {
      const tr = h("tr", { tabIndex: 0, class: row === selected ? "sel" : "",
        onclick: () => select(row), ondblclick: () => { select(row); onOpen(row); },
        onkeydown: (e) => {
          if (e.key === "Enter") { select(row); onOpen(row); }
          else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const i = list.indexOf(row) + (e.key === "ArrowDown" ? 1 : -1);
            if (list[i]) { select(list[i]); tbody.children[i]?.focus(); }
          }
        } },
        columns.map((c) => h("td", { class: c.align === "right" ? "num" : "" }, c.render ? c.render(row) : String(row[c.key] ?? "—"))));
      return tr;
    }));
  }
  return {
    el,
    setRows(next) {
      rows = next;
      if (selected && !rows.some((r) => getKey(r) === getKey(selected))) { selected = null; onSelect(null); }
      else if (selected) selected = rows.find((r) => getKey(r) === getKey(selected));
      draw();
    },
    refresh: draw,
    getSelected: () => selected,
  };
}
