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
