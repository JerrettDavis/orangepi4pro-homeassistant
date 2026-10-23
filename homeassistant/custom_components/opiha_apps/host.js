import {Tab, esc} from "./common.js";

const SECTIONS = [["services", "Services"], ["journal", "Journal"], ["hardware", "Hardware"]];

class HostTab extends Tab {
  interval = 10000;
  section = "services"; filter = "all"; search = ""; services = null; hardware = null;
  journal = {unit: "", lines: 300, priority: "", boot: false, text: null};
  async load() {
    if (this.section === "services") this.services = (await this.ws("services")).services;
    else if (this.section === "hardware" && !this.hardware) this.hardware = await this.ws("hardware");
    else if (this.section === "journal" && this.journal.text === null) await this.loadJournal();
  }
  async loadJournal() {
    const j = this.journal, data = {lines: j.lines, boot: j.boot};
    if (j.unit) data.unit = j.unit; if (j.priority) data.priority = j.priority;
    j.text = (await this.ws("logs", data)).logs;
  }
  view() {
    const nav = `<div class="seg" role="tablist">${SECTIONS.map(([id, label]) => `<button role="tab" aria-selected="${id === this.section}" class="${id === this.section ? "active" : ""}" data-section="${id}">${label}</button>`).join("")}</div>`;
    return nav + this[this.section + "View"]();
  }
  servicesView() {
    if (!this.services) return `<div class="empty">Reading services…</div>`;
    const q = this.search.toLowerCase();
    const rows = this.services.filter(s => (this.filter === "all" || (this.filter === "running" && s.sub === "running") || (this.filter === "failed" && s.active === "failed") || (this.filter === "enabled" && s.enabled === "enabled"))
      && `${s.unit} ${s.description}`.toLowerCase().includes(q));
    const tone = (s) => s.active === "failed" ? "bad" : s.sub === "running" ? "good" : "";
    return `<div class="row" style="margin-bottom:12px"><input id="search" class="grow" type="search" placeholder="Find a service" aria-label="Find a service" value="${esc(this.search)}">
      ${["all", "running", "failed", "enabled"].map(f => `<button class="small ${this.filter === f ? "active" : ""}" data-filter="${f}">${f[0].toUpperCase() + f.slice(1)}</button>`).join("")}</div>
      <div class="wrap"><table><thead><tr><th>Service</th><th>State</th><th>Boot</th><th>Description</th><th class="actions"></th></tr></thead><tbody>
      ${rows.map(s => `<tr><td><strong>${esc(s.unit.replace(/\.service$/, ""))}</strong></td><td><span class="badge ${tone(s)}">${esc(s.active === "active" ? s.sub : s.active)}</span></td><td>${esc(s.enabled || "–")}</td><td class="muted">${esc(s.description)}</td>
        <td class="actions">${s.sub === "running" ? "" : `<button class="small" data-svc="${esc(s.unit)}" data-act="start">Start</button>`}
        ${s.sub === "running" && !s.lifeline ? `<button class="small" data-svc="${esc(s.unit)}" data-act="stop">Stop</button>` : ""}<button class="small" data-svc="${esc(s.unit)}" data-act="restart">Restart</button>
        ${s.lifeline ? "" : `<button class="small" data-svc="${esc(s.unit)}" data-act="${s.enabled === "enabled" ? "disable" : "enable"}">${s.enabled === "enabled" ? "Disable" : "Enable"}</button>`}
        <button class="small" data-svc="${esc(s.unit)}" data-act="logs">Logs</button></td></tr>`).join("")}</tbody></table></div>
      ${rows.length ? "" : `<div class="empty">No matching services.</div>`}`;
  }
  journalView() {
    const j = this.journal;
    return `<form id="jform" class="row" style="margin-bottom:12px"><input id="junit" class="grow" placeholder="Unit, e.g. docker.service (blank for everything)" value="${esc(j.unit)}" aria-label="Unit">
      <select id="jprio" aria-label="Minimum priority"><option value="">Any priority</option>${["err", "warning", "notice", "info"].map(p => `<option ${j.priority === p ? "selected" : ""}>${p}</option>`).join("")}</select>
      <select id="jlines" aria-label="Lines">${[100, 300, 1000, 2000].map(n => `<option ${j.lines === n ? "selected" : ""}>${n}</option>`).join("")}</select>
      <label class="row"><input id="jboot" type="checkbox" ${j.boot ? "checked" : ""}> This boot</label><button class="primary">Load</button></form>
      <pre id="jtext">${esc(j.text ?? "Loading…")}</pre>`;
  }
  hardwareView() {
    if (!this.hardware) return `<div class="empty">Reading hardware…</div>`;
    const flat = (list, depth = 0) => list.flatMap(d => [{...d, depth}, ...flat(d.children || [], depth + 1)]);
    return `<h2>Block devices</h2><div class="wrap"><table><thead><tr><th>Device</th><th>Size</th><th>Type</th><th>Filesystem</th><th>Mount</th></tr></thead><tbody>
      ${flat(this.hardware.block_devices).map(d => `<tr><td style="padding-left:${12 + d.depth * 18}px">${esc(d.name)}${d.model ? ` <span class="muted">${esc(d.model)}</span>` : ""}</td><td>${esc(d.size)}</td><td>${esc(d.type)}</td><td>${esc(d.fstype || "")}</td><td>${esc(d.mountpoint || "")}</td></tr>`).join("")}</tbody></table></div>
      <h2 style="margin-top:20px">USB devices</h2><pre>${esc(this.hardware.usb.join("\n") || "None reported")}</pre>`;
  }
  bind() {
    this.$$("[data-section]").forEach(b => b.onclick = () => { this.section = b.dataset.section; this.draw(); this.refresh(); });
    this.$$("[data-filter]").forEach(b => b.onclick = () => { this.filter = b.dataset.filter; this.draw(); });
    const search = this.$("#search");
    if (search) search.oninput = () => { this.search = search.value; const pos = search.selectionStart; this.draw(); const again = this.$("#search"); again.focus(); try { again.setSelectionRange(pos, pos); } catch {} };
    this.$$("[data-svc]").forEach(b => b.onclick = () => this.service(b.dataset.svc, b.dataset.act));
    const form = this.$("#jform");
    if (form) form.onsubmit = async (e) => {
      e.preventDefault(); const j = this.journal;
      j.unit = this.$("#junit").value.trim(); j.priority = this.$("#jprio").value; j.lines = Number(this.$("#jlines").value); j.boot = this.$("#jboot").checked;
      try { await this.loadJournal(); } catch (err) { j.text = err.message; } this.draw();
    };
  }
  async service(unit, action) {
    if (action === "logs") {
      try { const r = await this.ws("logs", {unit, lines: 300}); this.modal(unit, `<pre>${esc(r.logs)}</pre><div class="buttons"><button data-close>Close</button></div>`); } catch (e) { this.fail(e); }
      return;
    }
    const risky = ["stop", "restart", "disable"].includes(action);
    if (risky && !await this.confirm(`${action[0].toUpperCase() + action.slice(1)} ${unit}?`, `This runs <code>systemctl ${esc(action)} ${esc(unit)}</code> on the host.${unit === "orangepi-apps.service" ? " This panel reconnects after a few seconds." : ""}`, action[0].toUpperCase() + action.slice(1), action !== "restart")) return;
    if (await this.act("service", {unit, action, confirm: risky ? true : undefined}, `${action} ${unit}: done`)) this.refresh();
  }
}
if (!customElements.get("opiha-host-tab")) customElements.define("opiha-host-tab", HostTab);
