import {Tab, esc} from "./common.js";

class UpdatesTab extends Tab {
  interval = 3000;
  info = null; job = null;
  async load() {
    this.job = await this.ws("update_job");
    // The package scan is slow, so it is read once, then again whenever a job has just finished.
    if (!this.info || (this.lastState === "running" && this.job.state !== "running")) this.info = await this.ws("updates");
    this.lastState = this.job.state;
  }
  view() {
    const i = this.info, job = this.job; if (!i) return `<div class="empty">Checking for updates (this can take a few seconds)…</div>`;
    const running = job?.state === "running";
    const refreshed = i.refreshed ? new Date(i.refreshed * 1000).toLocaleString() : "unknown";
    return `${i.reboot.required ? `<div class="notice warn" role="status"><strong>Reboot required.</strong> ${i.reboot.packages.length ? "Updated: " + esc(i.reboot.packages.join(", ")) + ". " : ""}<button id="reboot" class="small" style="margin-left:8px">Reboot…</button></div>` : ""}
      <div class="row" style="margin-bottom:16px"><div class="grow"><h2 style="margin:0">Host packages</h2><span class="muted">Package lists refreshed ${esc(refreshed)} · ${i.packages.length} upgradable${i.held.length ? " · held: " + esc(i.held.join(", ")) : ""}</span></div>
        <button id="check" ${running ? "disabled" : ""}>Check for updates</button><button id="upgrade" class="primary" ${running || !i.packages.length ? "disabled" : ""}>Upgrade ${i.packages.length || ""} package${i.packages.length === 1 ? "" : "s"}…</button></div>
      ${i.packages.length ? `<div class="wrap"><table><thead><tr><th>Package</th><th>Installed</th><th>Available</th><th>Source</th></tr></thead><tbody>${i.packages.map(p => `<tr><td><strong>${esc(p.name)}</strong></td><td class="muted">${esc(p.from || "–")}</td><td>${esc(p.version)}</td><td class="muted">${esc(p.suite)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="card empty">The host packages are up to date.</div>`}
      <div class="row" style="margin:24px 0 12px"><div class="grow"><h2 style="margin:0">Snaps</h2><span class="muted">${i.snaps.length ? i.snaps.length + " refresh" + (i.snaps.length > 1 ? "es" : "") + " available" : "All snaps are current"}. Refreshing Firefox restarts the kiosk browser.</span></div>
        <button id="snap" ${running || !i.snaps.length ? "disabled" : ""}>Refresh snaps…</button></div>
      ${i.snaps.length ? `<div class="wrap"><table><thead><tr><th>Snap</th><th>Version</th><th>Revision</th></tr></thead><tbody>${i.snaps.map(s => `<tr><td><strong>${esc(s.name)}</strong></td><td>${esc(s.version)}</td><td>${esc(s.revision)}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${job && job.state !== "none" ? `<h2 style="margin:24px 0 8px">${esc(job.description || "Last operation")} <span class="badge ${job.state === "succeeded" ? "good" : job.state === "failed" ? "bad" : "warn"}">${esc(job.state)}</span></h2><pre id="log">${esc(job.log || "")}</pre>` : ""}
      <p class="muted" style="margin-top:18px">Upgrades run on the host outside this panel, so they continue if the panel or manager restarts. Check the list before upgrading: kernel, bootloader and board-support packages on this device come from the vendor image.</p>`;
  }
  bind() {
    const log = this.$("#log"); if (log) log.scrollTop = log.scrollHeight;
    const start = (kind, title, body, label) => async () => {
      if (!await this.confirm(title, body, label, kind === "apt-upgrade")) return;
      if (await this.act("update_start", {kind, confirm: true}, "Started")) { this.job = {state: "running", description: title, log: ""}; this.lastState = "running"; this.draw(); this.refresh(); }
    };
    const check = this.$("#check"), up = this.$("#upgrade"), snap = this.$("#snap"), reboot = this.$("#reboot");
    if (check) {
      check.onclick = start("apt-update", "Refresh package lists", "Downloads the latest package lists. Nothing is installed.", "Refresh");
      up.onclick = start("apt-upgrade", "Upgrade host packages", `Installs ${this.info.packages.length} package update(s) with <code>apt-get upgrade</code>. Existing configuration files are kept. Services may restart; a reboot may be needed afterwards.`, "Upgrade");
      snap.onclick = start("snap-refresh", "Refresh snaps", "Updates snaps, including Firefox for the kiosk, which restarts the browser.", "Refresh");
    }
    if (reboot) reboot.onclick = async () => { if (await this.confirm("Reboot this host?", "Home Assistant, the kiosk and every app restart.", "Reboot", true)) this.act("power", {action: "reboot", confirm: true}, "Rebooting in a few seconds"); };
  }
}
if (!customElements.get("opiha-updates-tab")) customElements.define("opiha-updates-tab", UpdatesTab);
