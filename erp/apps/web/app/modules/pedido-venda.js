// Faturamento · Pedido de Venda (M15): lista de pedidos e visualização em pastas.
import { api } from "../core/api.js";
import { session } from "../core/session.js";
import { createGrid } from "../core/grid.js";
import { h, money, qty, shortId, badge, field, openDialog, toast, LABELS } from "../core/ui.js";

const PAGE = 50;

export const pedidoVenda = {
  id: "pedido-venda",
  title: "Pedido de Venda",
  group: "Faturamento",
  code: "M15",
  permission: "sales.order.read",
  mount(pane) {
    let orders = [];
    let page = 1;
    let hasMore = false;
    let cache = new Map(); // "kind:id" -> Promise<string>

    // Nomes de cliente e produto (a API de pedidos devolve só ids).
    function nameOf(kind, id) {
      const key = `${session.company}:${kind}:${id}`;
      if (!cache.has(key)) {
        cache.set(key, api(`${kind}/${id}?${session.q}`)
          .then((r) => (kind === "customers" ? r.trade_name || r.legal_name : `${r.code} · ${r.name}`))
          .catch(() => shortId(id)));
      }
      return cache.get(key);
    }

    const grid = createGrid({
      getKey: (o) => o.id,
      onSelect: (o) => { bView.disabled = !o; },
      onOpen: (o) => openOrder(o),
      empty: "Nenhum pedido encontrado.",
      columns: [
        { key: "number", label: "Número" },
        { key: "customerName", label: "Cliente", render: (o) => o.customerName || shortId(o.customer_id) },
        { key: "status", label: "Situação", render: (o) => badge(o.status), sortValue: (o) => LABELS[o.status] || o.status },
        { key: "gross_amount", label: "Valor bruto", align: "right", render: (o) => money(o.gross_amount, o.currency), sortValue: (o) => Number(o.gross_amount) },
        { key: "discount_amount", label: "Desconto", align: "right", render: (o) => money(o.discount_amount, o.currency), sortValue: (o) => Number(o.discount_amount) },
        { key: "net_amount", label: "Valor líquido", align: "right", render: (o) => money(o.net_amount, o.currency), sortValue: (o) => Number(o.net_amount) },
        { key: "source_quote_id", label: "Cotação", render: (o) => `${shortId(o.source_quote_id)} · rev. ${o.source_quote_revision_number}` },
      ],
    });

    const status = h("select", { id: "pv-status", onchange: apply },
      h("option", { value: "" }, "Todas"),
      ...["DRAFT", "APPROVED", "CANCELLED", "COMPLETED"].map((s) => h("option", { value: s }, LABELS[s])));
    const find = h("input", { type: "search", placeholder: "Número ou cliente", autocomplete: "off", oninput: apply });
    const count = h("span", { class: "muted" });
    const more = h("button", { type: "button", class: "btn", hidden: true, onclick: () => load(page + 1) }, "Carregar mais");
    const bView = h("button", { type: "button", class: "btn", disabled: true, onclick: () => grid.getSelected() && openOrder(grid.getSelected()) }, "Visualizar");
    const bRefresh = h("button", { type: "button", class: "btn", onclick: () => load(1) }, "Atualizar");

    pane.append(
      h("div", { class: "title" }, h("h1", {}, "Pedidos de Venda"), h("span", { class: "muted" }, "Faturamento · M15 · Browse")),
      h("div", { class: "filterbar" },
        h("label", {}, "Situação ", status), h("label", {}, "Localizar ", find), bRefresh),
      h("div", { class: "actionbar", role: "toolbar", "aria-label": "Ações" }, bView),
      grid.el,
      h("div", { class: "pager" }, count, more));

    function apply() {
      const term = find.value.trim().toLowerCase();
      const list = orders.filter((o) =>
        (!status.value || o.status === status.value) &&
        (!term || `${o.number} ${o.customerName || ""}`.toLowerCase().includes(term)));
      grid.setRows(list);
      count.textContent = `${list.length} de ${orders.length} pedido(s) carregado(s)`;
    }

    async function load(target = 1) {
      if (!session.can("sales.order.read")) return;
      try {
        const res = await api(`sales/orders?${session.q}&page=${target}&page_size=${PAGE}`);
        page = target;
        hasMore = Boolean(res.meta?.has_more);
        orders = target === 1 ? res.data : [...orders, ...res.data];
        more.hidden = !hasMore;
        apply();
        const ids = [...new Set(res.data.map((o) => o.customer_id))];
        await Promise.all(ids.map(async (id) => {
          const name = await nameOf("customers", id);
          orders.filter((o) => o.customer_id === id).forEach((o) => { o.customerName = name; });
        }));
        apply();
      } catch (error) {
        toast(error.message, "error");
      }
    }

    async function openOrder(summary) {
      try {
        const o = await api(`sales/orders/${summary.id}?${session.q}`);
        const [customer, ...products] = await Promise.all([
          nameOf("customers", o.customer_id), ...o.items.map((i) => nameOf("products", i.product_id))]);
        const lines = o.items.map((it, n) => {
          const total = Number(it.quantity) * Number(it.unit_price) - Number(it.discount_amount);
          return h("tr", {}, h("td", {}, String(n + 1)), h("td", {}, products[n]),
            h("td", { class: "num" }, qty(it.quantity)), h("td", { class: "num" }, money(it.unit_price, o.currency)),
            h("td", { class: "num" }, money(it.discount_amount, o.currency)), h("td", { class: "num" }, money(total, o.currency)));
        });
        openDialog({
          title: `Pedido ${o.number}`, subtitle: "Visualizar",
          folders: [
            { label: "Cabeçalho", content: h("div", { class: "form-grid" },
              field("Número", o.number), field("Situação", badge(o.status)), field("Moeda", o.currency),
              field("Cliente", customer, "w2"), field("Vendedor", shortId(o.seller_id)),
              field("Valor bruto", money(o.gross_amount, o.currency)), field("Desconto", money(o.discount_amount, o.currency)),
              field("Valor líquido", money(o.net_amount, o.currency))) },
            { label: `Itens (${o.items.length})`, content: h("div", { class: "grid" }, h("table", {},
              h("thead", {}, h("tr", {}, ["#", "Produto", "Quantidade", "Preço unit.", "Desconto", "Total"].map((t, i) => h("th", { class: i > 1 ? "num" : "" }, t)))),
              h("tbody", {}, lines))) },
            { label: "Origem", content: h("div", { class: "form-grid" },
              field("Cotação", shortId(o.source_quote_id)), field("Revisão", String(o.source_quote_revision_number)),
              field("Versão do pedido", String(o.version)),
              ...o.items.map((it, n) => field(`Preço do item ${n + 1}`, it.pricing_snapshot_id ? `snapshot ${shortId(it.pricing_snapshot_id)}` : "sem snapshot"))) },
          ],
        });
      } catch (error) {
        toast(error.message, "error");
      }
    }

    load(1);
    return {
      refresh() { cache = new Map(); orders = []; apply(); load(1); },
      activated() { grid.refresh(); },
    };
  },
};
