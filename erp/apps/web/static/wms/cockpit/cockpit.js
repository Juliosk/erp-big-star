const $ = (id) => document.getElementById(id);
let token = "";
let noticeTimer = 0;

const statusLabel = { DRAFT: "Separação", PACKING: "Packing", MANIFESTED: "Manifestada" };
const storageLabel = { PICKING: "Picking", BULK: "Pulmão", DAMAGE: "Avaria", QUARANTINE: "Quarentena" };

async function api(path) {
  const response = await fetch(`/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  let body = null;
  try { body = await response.json(); } catch { /* resposta sem JSON */ }
  if (!response.ok) {
    const error = new Error(body?.error?.message || "Não foi possível carregar o WMS.");
    error.status = response.status;
    throw error;
  }
  return body;
}
function number(value, digits = 0) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits }).format(Number(value));
}
function dateTime(value) {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
function notify(message) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").classList.add("visible");
  noticeTimer = window.setTimeout(() => $("notice").classList.remove("visible"), 2800);
}
function textElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}
function fillClass(value) {
  return `fill-${Math.max(0, Math.min(10, Math.round(Number(value) / 10)))}`;
}

function renderZones(zones) {
  $("zones-empty").hidden = zones.length > 0;
  $("zones").replaceChildren(...zones.map((zone) => {
    const card = document.createElement("article");
    card.className = `zone-card zone-${zone.storage_type.toLowerCase()}`;
    const header = document.createElement("header");
    header.append(
      textElement("span", "zone-code", `ZONA ${zone.code}`),
      textElement("span", "zone-type", storageLabel[zone.storage_type] || zone.storage_type),
    );
    const value = textElement("strong", "zone-percent", `${number(zone.occupancy_percent, 1)}%`);
    const track = document.createElement("div");
    track.className = "occupancy-track";
    track.setAttribute("aria-label", `Ocupação ${number(zone.occupancy_percent, 1)}%`);
    track.append(textElement("i", fillClass(zone.occupancy_percent), ""));
    const facts = document.createElement("div");
    facts.className = "zone-facts";
    facts.append(
      textElement("span", "", `${zone.occupied_bins}/${zone.bin_count} bins ocupados`),
      textElement("span", "", `${zone.blocked_bins} bloqueados`),
      textElement("span", "", `${zone.occupied_units}/${zone.max_units} un.`),
    );
    card.append(header, value, track, facts);
    return card;
  }));
}

function renderWaves(waves) {
  $("waves-empty").hidden = waves.length > 0;
  $("wave-count").textContent = `${waves.length} onda(s) exibida(s)`;
  $("waves").replaceChildren(...waves.map((wave) => {
    const row = document.createElement("tr");
    const route = wave.next_address || wave.first_address || "Sem rota";
    const values = [
      ["Onda", wave.code, "mono"],
      ["Status", statusLabel[wave.status] || wave.status, `pill ${wave.status === "MANIFESTED" ? "good" : "warn"}`],
      ["Rota", route, "route-address"],
      ["Progresso", `${number(wave.progress_percent, 1)}%`, ""],
      ["Conferência", `${wave.packed_items}/${wave.item_count} embalados`, ""],
      ["Atualização", dateTime(wave.updated_at), ""],
    ];
    values.forEach(([label, value, className]) => {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      if (label === "Progresso") {
        const text = textElement("strong", "", value);
        const track = document.createElement("div");
        track.className = "wave-track";
        track.append(textElement("i", fillClass(wave.progress_percent), ""));
        cell.append(text, track);
      } else {
        cell.append(textElement("span", className, value));
      }
      row.append(cell);
    });
    return row;
  }));
}

function renderQueue(entries) {
  $("queue-empty").hidden = entries.length > 0;
  $("dispatch-queue").replaceChildren(...entries.map((entry) => {
    const card = document.createElement("article");
    card.className = "queue-card";
    const header = document.createElement("header");
    header.append(
      textElement("strong", "mono", entry.wave_code),
      textElement("span", "pill warn", statusLabel[entry.status] || entry.status),
    );
    const detail = textElement(
      "p",
      "",
      `${entry.pending_pick_items} para separar · ${entry.pending_pack_items} para conferir · ${entry.ready_items} prontos`,
    );
    card.append(header, detail);
    return card;
  }));
}

function render(snapshot) {
  $("generated").textContent = `Atualizado em ${dateTime(snapshot.generated_at)}`;
  $("metric-waves").textContent = String(snapshot.dispatch_queue.length);
  $("metric-occupancy").textContent = `${number(snapshot.occupancy_percent, 1)}%`;
  $("metric-blocked").textContent = String(snapshot.blocked_bins);
  renderZones(snapshot.zones);
  renderWaves(snapshot.waves);
  renderQueue(snapshot.dispatch_queue);
}

async function load({ announce = false } = {}) {
  const companyId = $("company").value;
  if (!companyId) return;
  $("refresh").disabled = true;
  try {
    render(await api(`wms/cockpit?company_id=${encodeURIComponent(companyId)}`));
    if (announce) notify("WMS atualizado com a posição física mais recente.");
  } catch (error) {
    if (error.status === 401 || error.status === 403) showDenied();
    else notify(error.message);
  } finally {
    $("refresh").disabled = false;
  }
}
function showDenied() {
  $("access").hidden = true;
  $("cockpit").hidden = true;
  $("denied").hidden = false;
}

$("access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = $("access-token").value.trim();
  $("access-error").textContent = "";
  if (!token) return;
  try {
    const context = await api("admin/session-context");
    if (!context.permissions.includes("wms.inventory.read")) {
      showDenied();
      return;
    }
    const companies = (await api("admin/companies?status=ACTIVE")).items;
    $("company").replaceChildren(...companies.map((company) => {
      const option = document.createElement("option");
      option.value = company.id;
      option.textContent = company.trade_name || company.legal_name;
      return option;
    }));
    $("access-token").value = "";
    $("access").hidden = true;
    $("cockpit").hidden = false;
    await load();
  } catch (error) {
    $("access-error").textContent = error.message;
  }
});
$("company").addEventListener("change", () => load({ announce: true }));
$("refresh").addEventListener("click", () => load({ announce: true }));
$("denied-back").addEventListener("click", () => {
  token = "";
  $("denied").hidden = true;
  $("access").hidden = false;
  $("access-token").focus();
});
$("access-token").focus();
