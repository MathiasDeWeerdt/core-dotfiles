"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const PREFIXES = [30, 29, 28, 27, 26, 25, 24, 23, 22, 20, 16];
const LEASE_TIMES = [
  ["1h", "1 hour"],
  ["6h", "6 hours"],
  ["12h", "12 hours"],
  ["1d", "1 day"],
  ["7d", "7 days"],
  ["infinite", "Forever"],
];

const S = {
  active: false,
  config: {},
  network: null,
  leases: [],
  reservations: [],
  interfaces: [],
  started_at: null,
  root: true,
};

let selected = { wan: "", lan: "" };
let lastAutoRange = null;
let pollTimer = null;

const appEl = $("#app");

/* ------------------------------------------------------------------ utils */

function pushToast(node, duration) {
  const box = $("#toasts");
  box.appendChild(node);
  requestAnimationFrame(() => node.classList.add("show"));
  while (box.children.length > 3) box.removeChild(box.firstChild);
  setTimeout(() => {
    node.classList.remove("show");
    setTimeout(() => node.remove(), 300);
  }, duration);
}

function toast(message, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  pushToast(el, 3200);
}

function notifyDevice(name, online) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span class="tdot ${online ? "online" : "offline"}"></span><span>${esc(name)} ${online ? "came online" : "went offline"}</span>`;
  pushToast(el, 2600);
}

async function api(path, options = {}) {
  const opts = { headers: { "Content-Type": "application/json" }, ...options };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error("Cannot reach the server.");
  }
  const data = await res.json().catch(() => ({ ok: false, error: "Invalid server response" }));
  if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function icon(kind) {
  const a = 'viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
  if (kind === "wifi")
    return `<svg ${a}><path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1.1" fill="currentColor" stroke="none"/></svg>`;
  if (kind === "ethernet" || kind === "other")
    return `<svg ${a}><rect x="3" y="8" width="18" height="11" rx="2.5"/><path d="M7 8V5.5h10V8"/><path d="M8 19v2.2M16 19v2.2"/></svg>`;
  if (kind === "bridge")
    return `<svg ${a}><rect x="3" y="9" width="7" height="6" rx="1.5"/><rect x="14" y="9" width="7" height="6" rx="1.5"/><path d="M10 12h4"/></svg>`;
  if (kind === "tunnel")
    return `<svg ${a}><path d="M8 8v8M16 8v8M8 12h8"/><rect x="3" y="5" width="18" height="14" rx="2.5"/></svg>`;
  return `<svg ${a}><circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/></svg>`;
}

const CHECK = `<span class="iface-check"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7"/></svg></span>`;

function fmtUptime(seconds) {
  if (!seconds || seconds < 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return "< 1m";
}

function fmtRemaining(sec) {
  if (sec === null) return "static";
  if (sec <= 0) return "expiring";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function suggestRange(ip) {
  const parts = String(ip).split(".").map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n) || n < 0 || n > 255)) return null;
  const base = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3];
  const ipToStr = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join(".");
  return { start: ipToStr(base + 49), end: ipToStr(base + 199) };
}

function setBusy(btn, busy, label) {
  if (!btn) return;
  if (busy) {
    btn._label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>${label || "Working…"}`;
  } else {
    btn.disabled = false;
    if (btn._label) btn.innerHTML = btn._label;
  }
}

/* ---------------------------------------------------------- data loading */

async function load() {
  const data = await api("/api/state");
  S.active = data.state.active;
  S.config = data.state.config;
  S.network = data.state.network;
  S.leases = data.state.leases;
  S.reservations = data.state.reservations;
  S.started_at = data.state.started_at;
  S.interfaces = data.interfaces;
  S.root = data.root;

  lastAutoRange = null;
  if (!selected.wan) selected.wan = S.config.wan || defaultWan();
  if (!selected.lan) selected.lan = S.config.lan || defaultLan();

  $("#root-note").textContent = S.root
    ? ""
    : "Not running as root — changes will be rejected. Restart with sudo.";

  render();
}

function defaultWan() {
  const d = S.interfaces.find((i) => i.is_default);
  return d ? d.name : S.interfaces[0] ? S.interfaces[0].name : "";
}

function defaultLan() {
  const c = S.interfaces.find((i) => i.name !== selected.wan && (i.kind === "ethernet" || i.kind === "wifi"));
  return c ? c.name : "";
}

function applyStatus(st) {
  S.active = st.active;
  S.config = st.config;
  S.network = st.network;
  S.leases = st.leases || [];
  S.reservations = st.reservations || [];
  S.started_at = st.started_at;
  lastAutoRange = null;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/* -------------------------------------------------------------- rendering */

function render() {
  stopPolling();
  appEl.innerHTML = "";
  if (S.active) {
    renderActive();
    pollTimer = setInterval(refreshLeases, 1000);
  } else {
    renderSetup();
  }
}

const KIND_LABELS = { wifi: "Wi-Fi", ethernet: "Ethernet", bridge: "Bridge", tunnel: "Tunnel" };
const kindLabel = (kind) => KIND_LABELS[kind] || "Network";

function lanIsWifi() {
  const iface = S.interfaces.find((i) => i.name === selected.lan);
  return !!iface && iface.kind === "wifi";
}

function wifiFields(cfg) {
  return `
    <div class="field ${lanIsWifi() ? "" : "hidden"}" data-wifi>
      <label>Wi-Fi network</label>
      <div class="grid-2">
        <div class="subfield" style="margin-top:0">
          <span class="sub-label">Name (SSID)</span>
          <input type="text" data-f="wifi_ssid" value="${esc(cfg.wifi_ssid || "jimber")}" placeholder="jimber" spellcheck="false" />
        </div>
        <div class="subfield" style="margin-top:0">
          <span class="sub-label">Password</span>
          <input type="text" data-f="wifi_password" value="${esc(cfg.wifi_password || "applebananaorange")}" placeholder="applebananaorange" spellcheck="false" />
        </div>
      </div>
      <p class="muted" style="margin:10px 0 0;font-size:12.5px">Devices join this network to get online.</p>
    </div>`;
}

function updateWifiFields(root) {
  const el = root.querySelector("[data-wifi]");
  if (el) el.classList.toggle("hidden", !lanIsWifi());
}

function ifaceCard(iface, role) {
  const isSel = selected[role] === iface.name;
  const addr = iface.addresses.length ? iface.addresses.join(", ") : "No address";
  const stateTxt = iface.carrier === false ? "disconnected" : iface.state;
  const badge = iface.is_default ? '<span class="badge">Internet</span>' : "";
  return `
    <button class="iface ${isSel ? "selected" : ""}" data-role="${role}" data-name="${esc(iface.name)}">
      <span class="iface-icon">${icon(iface.kind)}</span>
      <span class="iface-meta">
        <span class="iface-name">${esc(iface.name)}${badge}</span>
        <span class="iface-sub">${esc(kindLabel(iface.kind))} · ${esc(addr)} · ${esc(stateTxt)}</span>
      </span>
      ${CHECK}
    </button>`;
}

function prefixOptions(sel) {
  return PREFIXES.map((p) => {
    const mask = [(0xffffffff << (32 - p)) >>> 24 & 255, (0xffffffff << (32 - p)) >>> 16 & 255,
      (0xffffffff << (32 - p)) >>> 8 & 255, (0xffffffff << (32 - p)) & 255].join(".");
    return `<option value="${p}" ${p === sel ? "selected" : ""}>/${p} · ${mask}</option>`;
  }).join("");
}

function leaseTimeOptions(sel) {
  return LEASE_TIMES.map(([v, label]) => `<option value="${v}" ${v === sel ? "selected" : ""}>${label}</option>`).join("");
}

function advancedFields(cfg) {
  const join = (v) => esc((v || []).join(", "));
  return `
    <details class="advanced">
      <summary>Advanced</summary>
      <div class="subfield" style="margin-top:6px">
        <span class="sub-label">Domain name</span>
        <input type="text" data-f="domain" value="${esc(cfg.domain || "lan")}" placeholder="lan" spellcheck="false" />
      </div>
      <div class="subfield" style="margin-top:14px">
        <span class="sub-label">Upstream DNS</span>
        <input type="text" data-f="dns_servers" value="${join(cfg.dns_servers)}" placeholder="Automatic (system)" spellcheck="false" />
      </div>
      <div class="subfield" style="margin-top:14px">
        <span class="sub-label">DNS given to clients</span>
        <input type="text" data-f="dhcp_dns" value="${join(cfg.dhcp_dns)}" placeholder="This gateway" spellcheck="false" />
      </div>
    </details>`;
}

function configFields(cfg) {
  return `
    <div class="field">
      <label>Internet (WAN)</label>
      <div class="iface-grid" data-role="wan">
        ${S.interfaces.map((i) => ifaceCard(i, "wan")).join("")}
      </div>
    </div>
    <div class="field">
      <label>Devices (LAN)</label>
      <div class="iface-grid" data-role="lan">
        ${S.interfaces.map((i) => ifaceCard(i, "lan")).join("")}
      </div>
    </div>
    ${wifiFields(cfg)}
    <div class="field">
      <label>DHCP range</label>
      <div class="range-row">
        <input type="text" data-f="dhcp_start" value="${esc(cfg.dhcp_start || "")}" placeholder="10.42.0.50" spellcheck="false" />
        <span class="dash">–</span>
        <input type="text" data-f="dhcp_end" value="${esc(cfg.dhcp_end || "")}" placeholder="10.42.0.200" spellcheck="false" />
      </div>
    </div>
    <div class="grid-2">
      <div class="subfield">
        <span class="sub-label">Gateway address</span>
        <input type="text" data-f="lan_ip" value="${esc(cfg.lan_ip || "")}" placeholder="10.42.0.1" spellcheck="false" />
      </div>
      <div class="subfield">
        <span class="sub-label">Subnet size</span>
        <select data-f="prefix">${prefixOptions(cfg.prefix || 24)}</select>
      </div>
    </div>
    <div class="subfield" style="margin-top:14px">
      <span class="sub-label">Lease time</span>
      <select data-f="lease_time">${leaseTimeOptions(cfg.lease_time || "12h")}</select>
    </div>
    ${advancedFields(cfg)}`;
}

function wireConfigFields(root) {
  if (root._wireInit) return;
  root._wireInit = true;

  root.addEventListener("click", (e) => {
    const btn = e.target.closest(".iface");
    if (!btn || !root.contains(btn)) return;
    selected[btn.dataset.role] = btn.dataset.name;
    const grid = root.querySelector(`.iface-grid[data-role="${btn.dataset.role}"]`);
    if (grid) grid.innerHTML = S.interfaces.map((i) => ifaceCard(i, btn.dataset.role)).join("");
    updateWifiFields(root);
  });

  root.addEventListener("input", (e) => {
    const ipInput = e.target.closest('[data-f="lan_ip"]');
    if (!ipInput) return;
    const range = suggestRange(ipInput.value);
    if (!range) return;
    const startEl = root.querySelector('[data-f="dhcp_start"]');
    const endEl = root.querySelector('[data-f="dhcp_end"]');
    if (!startEl || !endEl) return;
    const cur = { start: startEl.value, end: endEl.value };
    if (!lastAutoRange || (cur.start === lastAutoRange.start && cur.end === lastAutoRange.end)) {
      startEl.value = range.start;
      endEl.value = range.end;
      lastAutoRange = range;
    }
  });
}

function collectConfig(root) {
  const val = (f) => {
    const el = $(`[data-f="${f}"]`, root);
    return el ? el.value.trim() : undefined;
  };
  const list = (f) => {
    const v = val(f);
    return v ? v.split(",").map((s) => s.trim()).filter(Boolean) : [];
  };
  return {
    wan: selected.wan,
    lan: selected.lan,
    lan_ip: val("lan_ip"),
    prefix: parseInt(val("prefix"), 10),
    dhcp_start: val("dhcp_start"),
    dhcp_end: val("dhcp_end"),
    lease_time: val("lease_time"),
    domain: val("domain") || "jimber.local",
    dns_servers: list("dns_servers"),
    dhcp_dns: list("dhcp_dns"),
    wifi_ssid: lanIsWifi() ? val("wifi_ssid") || "jimber" : S.config.wifi_ssid || "jimber",
    wifi_password: lanIsWifi() ? val("wifi_password") || "" : S.config.wifi_password || "",
  };
}

/* ----------------------------------------------------------- setup view */

function renderSetup() {
  const cfg = S.config;
  const sec = document.createElement("section");
  sec.className = "card";
  sec.innerHTML = `
    <h2>Create a network</h2>
    <p class="muted">Pick where the internet comes from and where your devices connect. That's it.</p>
    ${configFields(cfg)}
    <button class="primary" id="start-btn">Start sharing</button>`;
  appEl.appendChild(sec);

  wireConfigFields(sec);
  $("#start-btn", sec).addEventListener("click", startSharing);
}

async function startSharing(e) {
  const btn = e.currentTarget;
  const cfg = collectConfig(appEl);
  setBusy(btn, true, "Starting…");
  try {
    const data = await api("/api/start", { method: "POST", body: JSON.stringify(cfg) });
    applyStatus(data.state);
    S.interfaces = data.interfaces || S.interfaces;
    toast("Sharing is on");
    render();
  } catch (err) {
    toast(err.message, true);
    setBusy(btn, false);
  }
}

/* ---------------------------------------------------------- active view */

function renderActive() {
  const cfg = S.config;
  const uptime = S.started_at ? Math.floor(Date.now() / 1000) - S.started_at : null;
  const nDevices = S.leases.filter((l) => l.online === true).length;

  const hero = document.createElement("section");
  hero.className = "card";
  hero.innerHTML = `
    <div class="hero">
      <span class="dot"></span>
      <div class="grow">
        <div class="hero-title">Sharing is on</div>
        <div class="hero-sub">${esc(cfg.wan)} → ${esc(cfg.lan)} · ${esc(S.network || "")}</div>
      </div>
      <label class="toggle" title="Stop sharing">
        <input type="checkbox" id="stop-toggle" checked />
        <span class="track"></span><span class="knob"></span>
      </label>
    </div>
    <div class="stats">
      <div class="stat"><div class="v" id="online-count">${nDevices}</div><div class="k">Online</div></div>
      <div class="stat"><div class="v" style="font-size:14px">${esc(cfg.dhcp_start)} – ${esc(cfg.dhcp_end)}</div><div class="k">DHCP range</div></div>
      <div class="stat"><div class="v">${fmtUptime(uptime)}</div><div class="k">Uptime</div></div>
    </div>`;
  appEl.appendChild(hero);
  $("#stop-toggle", hero).addEventListener("change", stopSharing);

  const devices = document.createElement("section");
  devices.className = "card";
  devices.innerHTML = `
    <div class="card-head">
      <h2>Devices</h2>
      <button class="ghost subtle" id="refresh-btn">Refresh</button>
    </div>
    <div class="list" id="leases-list"></div>`;
  appEl.appendChild(devices);
  renderLeases();
  $("#refresh-btn", devices).addEventListener("click", refreshLeases);

  const reserved = document.createElement("section");
  reserved.className = "card";
  reserved.innerHTML = `
    <div class="card-head">
      <h2>Reserved addresses</h2>
      <button class="ghost" id="add-res-btn">Add</button>
    </div>
    <div class="list" id="res-list"></div>`;
  appEl.appendChild(reserved);
  renderReservations();
  $("#add-res-btn", reserved).addEventListener("click", () => reservationSheet());

  const settings = document.createElement("section");
  settings.className = "card";
  settings.innerHTML = `<button class="ghost subtle" id="settings-btn">Network settings</button>`;
  appEl.appendChild(settings);
  $("#settings-btn", settings).addEventListener("click", settingsSheet);
}

function leaseRow(l) {
  const name = l.hostname ? esc(l.hostname) : "Unknown device";
  const badge = l.reserved ? '<span class="chip-static">reserved</span>' : "";
  const online = l.online === true;
  const dotCls = l.online === null || l.online === undefined ? "" : online ? "online" : "offline";
  const statusText = l.online === null || l.online === undefined ? "Checking…" : online ? "Online" : "Offline";
  return `
    <div class="row ${online ? "" : "is-offline"}">
      <div class="grow">
        <div class="name"><span class="status-dot ${dotCls}"></span>${name}${badge}</div>
        <div class="sub">${esc(l.mac)} · ${statusText} · ${esc(fmtRemaining(l.expires_in))}</div>
      </div>
      <div class="ip">${esc(l.ip)}</div>
      <div class="row-actions">
        <button class="ghost" data-pin="${esc(l.mac)}" data-ip="${esc(l.ip)}" data-host="${esc(l.hostname)}">Pin</button>
        <button class="ghost danger" data-forget="${esc(l.ip)}" data-mac="${esc(l.mac)}">Forget</button>
      </div>
    </div>`;
}

function renderLeases() {
  const box = $("#leases-list");
  if (!box) return;
  const active = S.leases.filter((l) => l.active);
  box.innerHTML = active.length
    ? active.map(leaseRow).join("")
    : `<div class="empty">No devices yet. Connect one to ${esc(S.config.lan)}.</div>`;

  $$("[data-forget]", box).forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/lease/delete", {
          method: "POST",
          body: JSON.stringify({ ip: btn.dataset.forget, mac: btn.dataset.mac }),
        });
        S.leases = data.leases;
        renderLeases();
        toast("Device forgotten");
      } catch (err) {
        toast(err.message, true);
      }
    })
  );
  $$("[data-pin]", box).forEach((btn) =>
    btn.addEventListener("click", () =>
      reservationSheet({ mac: btn.dataset.pin, ip: btn.dataset.ip, hostname: btn.dataset.host })
    )
  );
}

async function refreshLeases() {
  try {
    const data = await api("/api/leases");
    const prev = new Map(S.leases.map((l) => [l.ip, l.online]));
    const changed = JSON.stringify(data.leases) !== JSON.stringify(S.leases);
    data.leases.forEach((l) => {
      const was = prev.get(l.ip);
      if (was !== undefined && was !== null && l.online != null && was !== l.online) {
        notifyDevice(l.hostname || l.ip, l.online === true);
      }
    });
    S.leases = data.leases;
    if (changed) {
      renderLeases();
      const count = $("#online-count");
      if (count) count.textContent = S.leases.filter((l) => l.online === true).length;
    }
  } catch (_) {
    /* silent while polling */
  }
}

function renderReservations() {
  const box = $("#res-list");
  if (!box) return;
  box.innerHTML = S.reservations.length
    ? S.reservations
        .map(
          (r) => `
      <div class="row">
        <div class="grow">
          <div class="name">${r.hostname ? esc(r.hostname) : "Reserved"}</div>
          <div class="sub">${esc(r.mac)}</div>
        </div>
        <div class="ip">${esc(r.ip)}</div>
        <div class="row-actions">
          <button class="ghost danger" data-unreserve="${esc(r.mac)}">Remove</button>
        </div>
      </div>`
        )
        .join("")
    : `<div class="empty">No reserved addresses. Pin a device to keep its IP.</div>`;

  $$("[data-unreserve]", box).forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        const data = await api(`/api/reservations/${encodeURIComponent(btn.dataset.unreserve)}`, {
          method: "DELETE",
        });
        S.reservations = data.reservations;
        S.leases = data.leases;
        renderReservations();
        renderLeases();
        toast("Reservation removed");
      } catch (err) {
        toast(err.message, true);
      }
    })
  );
}

async function stopSharing() {
  try {
    const data = await api("/api/stop", { method: "POST" });
    applyStatus(data.state);
    S.interfaces = data.interfaces || S.interfaces;
    toast("Sharing stopped");
    render();
  } catch (err) {
    toast(err.message, true);
    render();
  }
}

/* ------------------------------------------------------------------ sheets */

function closeSheet() {
  const el = $("#sheet");
  el.hidden = true;
  $("#sheet-body").innerHTML = "";
}

function openSheet(html) {
  $("#sheet-body").innerHTML = html;
  $("#sheet").hidden = false;
}

function settingsSheet() {
  const cfg = S.config;
  openSheet(`
    <h2>Network settings</h2>
    <p class="muted">Changes apply immediately and briefly reconnect the network.</p>
    ${configFields(cfg)}
    <div class="actions-row">
      <button class="ghost subtle" id="cancel-btn" style="flex:1">Cancel</button>
      <button class="primary" id="save-btn" style="flex:2">Apply changes</button>
    </div>`);

  wireConfigFields($("#sheet-body"));

  $("#cancel-btn").addEventListener("click", closeSheet);
  $("#save-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    setBusy(btn, true, "Applying…");
    try {
      const data = await api("/api/config", { method: "POST", body: JSON.stringify(collectConfig($("#sheet-body"))) });
      applyStatus(data.state);
      S.interfaces = data.interfaces || S.interfaces;
      closeSheet();
      toast("Settings applied");
      render();
    } catch (err) {
      toast(err.message, true);
      setBusy(btn, false);
    }
  });
}

function reservationSheet(prefill = {}) {
  openSheet(`
    <h2>Reserve an address</h2>
    <p class="muted">Keep the same IP for a device every time it connects.</p>
    <div class="field">
      <label>MAC address</label>
      <input type="text" id="res-mac" value="${esc(prefill.mac || "")}" placeholder="aa:bb:cc:dd:ee:ff" spellcheck="false" />
    </div>
    <div class="field">
      <label>IP address</label>
      <input type="text" id="res-ip" value="${esc(prefill.ip || "")}" placeholder="10.42.0.50" spellcheck="false" />
    </div>
    <div class="field">
      <label>Name (optional)</label>
      <input type="text" id="res-host" value="${esc(prefill.hostname || "")}" placeholder="Living room TV" />
    </div>
    <div class="actions-row">
      <button class="ghost subtle" id="cancel-btn" style="flex:1">Cancel</button>
      <button class="primary" id="save-res-btn" style="flex:2">Save</button>
    </div>`);

  $("#cancel-btn").addEventListener("click", closeSheet);
  $("#save-res-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    setBusy(btn, true, "Saving…");
    try {
      const data = await api("/api/reservations", {
        method: "POST",
        body: JSON.stringify({
          mac: $("#res-mac").value,
          ip: $("#res-ip").value,
          hostname: $("#res-host").value,
        }),
      });
      S.reservations = data.reservations;
      S.leases = data.leases;
      closeSheet();
      renderReservations();
      renderLeases();
      toast("Address reserved");
    } catch (err) {
      toast(err.message, true);
      setBusy(btn, false);
    }
  });
}

/* -------------------------------------------------------------------- init */

$("#sheet").addEventListener("click", (e) => {
  if (e.target.id === "sheet") closeSheet();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSheet();
});

load().catch((err) => {
  appEl.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(err.message)}</p></div>`;
});
