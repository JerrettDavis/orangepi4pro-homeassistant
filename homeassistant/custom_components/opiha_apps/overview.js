import {Tab, esc, bytes, rate, duration, pct, spark, meter} from "./common.js";

const HISTORY = 60;

class OverviewTab extends Tab {
  interval = 4000;
  history = {cpu: [], mem: [], temp: []};
  async load() {
    const s = await this.ws("overview"); this.s = s;
    const push = (list, v) => { if (Number.isFinite(v)) { list.push(v); if (list.length > HISTORY) list.shift(); } };
    push(this.history.cpu, s.cpu_percent);
    push(this.history.mem, s.memory.total ? 100 * (1 - s.memory.available / s.memory.total) : NaN);
    push(this.history.temp, Math.max(...(s.temperatures.length ? s.temperatures.map(t => t.celsius) : [NaN])));
  }
  chips(s) {
    const out = [];
    const mode = {kiosk: "Kiosk mode", desktop: "Desktop mode", "no-session": "No desktop session", unavailable: "Desktop unavailable"}[s.desktop.mode] || s.desktop.mode;
    out.push(`<span class="chip good">${esc(mode)}</span>`);
    out.push(s.failed_services.length ? `<span class="chip bad">${s.failed_services.length} failed service${s.failed_services.length > 1 ? "s" : ""}: ${esc(s.failed_services.join(", "))}</span>` : `<span class="chip good">All services healthy</span>`);
    out.push(s.docker.error ? `<span class="chip bad">Docker: ${esc(s.docker.error)}</span>` : `<span class="chip">Docker ${s.docker.running}/${s.docker.containers} containers running</span>`);
    if (s.reboot.required) out.push(`<span class="chip warn">Reboot required${s.reboot.packages.length ? " · " + esc(s.reboot.packages.join(", ")) : ""}</span>`);
    if (s.job.state === "running") out.push(`<span class="chip warn">Update running: ${esc(s.job.description)}</span>`);
    return `<div class="chips">${out.join("")}</div>`;
  }
  view() {
    const s = this.s; if (!s) return `<div class="empty">Reading the host…</div>`;
    const m = s.memory, used = m.total - m.available, hot = s.temperatures.reduce((a, t) => t.celsius > (a?.celsius ?? -1) ? t : a, null);
    const swapUsed = (m.swap_total || 0) - (m.swap_free || 0);
    return `<div class="row" style="margin-bottom:12px"><button id="reboot">Reboot…</button><button id="poweroff" class="danger">Shut down…</button><button id="screen">Screen off</button></div>
      ${this.chips(s)}
      <div class="cards">
        <section class="card"><div class="label">CPU</div><div class="big">${pct(s.cpu_percent)}</div>${meter((s.cpu_percent || 0) / 100, "CPU use")}${spark(this.history.cpu)}
          <dl class="kv"><dt>Load</dt><dd>${s.load.join(" · ")} (${s.cpus} cores)</dd>${s.frequencies.length ? `<dt>Clock</dt><dd>${s.frequencies.map(f => f.mhz + " MHz").join(" · ")}</dd>` : ""}</dl></section>
        <section class="card"><div class="label">Memory</div><div class="big">${bytes(used)} <span class="muted" style="font-size:14px">of ${bytes(m.total)}</span></div>${meter(used / m.total, "Memory use")}${spark(this.history.mem)}
          <dl class="kv"><dt>Available</dt><dd>${bytes(m.available)}</dd><dt>Swap</dt><dd>${bytes(swapUsed)} of ${bytes(m.swap_total)}</dd></dl></section>
        <section class="card"><div class="label">Temperature</div><div class="big">${hot ? hot.celsius.toFixed(1) + " °C" : "–"}</div>${hot ? meter(hot.celsius / 100, "Temperature") : ""}${spark(this.history.temp, 100, "var(--warn)")}
          <dl class="kv">${s.temperatures.map(t => `<dt>${esc(t.name)}</dt><dd>${t.celsius.toFixed(1)} °C</dd>`).join("")}</dl></section>
        <section class="card"><div class="label">Storage</div>${s.disks.map(d => `<div style="margin-top:8px"><div class="row"><strong class="grow">${esc(d.mount)}</strong><span class="muted">${bytes(d.total - d.free)} of ${bytes(d.total)}</span></div>${meter((d.total - d.free) / d.total, d.mount)}</div>`).join("")}</section>
        <section class="card"><div class="label">Network</div>${s.network.map(n => `<div style="margin-top:8px"><strong>${esc(n.name)}</strong> <span class="muted">${esc(n.addresses.join(", "))}</span><div class="muted">↓ ${rate(n.rx_rate)} · ↑ ${rate(n.tx_rate)}</div></div>`).join("") || `<p class="muted">No interfaces</p>`}</section>
        <section class="card"><div class="label">System</div>
          <dl class="kv" style="margin-top:8px"><dt>Host</dt><dd>${esc(s.hostname)}</dd><dt>Board</dt><dd>${esc(s.model || "–")}</dd><dt>OS</dt><dd>${esc(s.os || "–")}</dd><dt>Kernel</dt><dd>${esc(s.kernel)} (${esc(s.arch)})</dd><dt>Uptime</dt><dd>${duration(s.uptime)}</dd></dl></section>
      </div>`;
  }
  bind() {
    const power = (action, label) => async () => {
      if (!await this.confirm(label + " this host?", action === "reboot" ? "Home Assistant, the kiosk and every app restart. The panel reconnects when the host is back, usually within a minute or two." : "The host powers off and stays off until someone presses its power button or restores power.", label, true)) return;
      if (await this.act("power", {action, confirm: true}, label + " in a few seconds")) this.s = null;
    };
    const reboot = this.$("#reboot"), off = this.$("#poweroff"), screen = this.$("#screen");
    if (reboot) { reboot.onclick = power("reboot", "Reboot"); off.onclick = power("poweroff", "Shut down"); screen.onclick = () => this.act("display", {action: "off"}, "Screen off; touch to wake"); }
  }
}
if (!customElements.get("opiha-overview-tab")) customElements.define("opiha-overview-tab", OverviewTab);
