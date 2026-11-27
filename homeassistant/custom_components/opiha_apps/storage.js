import {Tab, esc} from "./common.js";

const size = n => n >= 2 ** 30 ? (n / 2 ** 30).toFixed(1) + " GB" : (n / 2 ** 20).toFixed(0) + " MB";

class StorageTab extends Tab {
  interval = 5000;
  info = null; job = null;
  async load() {
    this.job = await this.ws("update_job");
    if (!this.info || (this.lastState === "running" && this.job.state !== "running")) this.info = await this.ws("storage");
    this.lastState = this.job.state;
  }
  view() {
    const i = this.info; if (!i) return `<div class="empty">Reading storage…</div>`;
    const running = this.job?.state === "running", pct = i.used_percent;
    const tone = pct >= 85 ? "bad" : pct >= 75 ? "warn" : "good";
    const autos = i.backups.filter(b => b.automatic);
    return `<div class="row" style="margin-bottom:16px"><div class="grow"><h2 style="margin:0">Root filesystem <span class="badge ${tone}">${pct}% used</span></h2>
        <span class="muted">${i.root ? size(i.root.free) + " free of " + size(i.root.total) : ""}. Aim to stay under 75% (25–33% free); 85% raises an alert. Light cleanup runs hourly on its own and goes deeper automatically at 75%.</span></div>
        <button id="light" ${running ? "disabled" : ""}>Free caches</button><button id="deep" class="primary" ${running ? "disabled" : ""}>Deep clean…</button>
        <button id="repack" ${running ? "disabled" : ""}>Purge &amp; repack recorder…</button></div>
      <div class="cards"><section class="card"><h3>Recorder database</h3><div>${size(i.recorder_bytes)}</div><span class="muted">Shrinks only after a purge &amp; repack; exclude noisy entities in the recorder configuration to keep it small.</span></section>
        <section class="card"><h3>Home Assistant backups</h3><div>${size(i.backups.reduce((s, b) => s + b.size, 0))} in ${i.backups.length} archive${i.backups.length === 1 ? "" : "s"}</div><span class="muted">Deep clean keeps the newest 3 automatic backups (${autos.length} now) and never touches manual ones.</span></section>
        ${i.docker.map(d => `<section class="card"><h3>Docker ${esc(d.type)}</h3><div>${esc(d.size)}</div><span class="muted">${esc(d.reclaimable)} reclaimable</span></section>`).join("")}</div>
      ${i.backups.length ? `<div class="wrap" style="margin-top:16px"><table><thead><tr><th>Backup</th><th>Size</th><th>Date</th></tr></thead><tbody>${i.backups.map(b => `<tr><td>${esc(b.name)} ${b.automatic ? "" : `<span class="badge">manual</span>`}</td><td>${size(b.size)}</td><td class="muted">${new Date(b.modified * 1000).toLocaleString()}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${this.job && this.job.state !== "none" ? `<h2 style="margin:24px 0 8px">${esc(this.job.description || "Last operation")} <span class="badge ${this.job.state === "succeeded" ? "good" : this.job.state === "failed" ? "bad" : "warn"}">${esc(this.job.state)}</span></h2><pre id="log">${esc(this.job.log || "")}</pre>` : ""}
      <p class="muted" style="margin-top:18px">Deep clean also removes unused Docker images and stopped containers that are not managed by Home Assistant. Last automatic run:</p><pre>${esc(i.last_guard_run || "no runs recorded")}</pre>`;
  }
  bind() {
    const start = (kind, title, body, label, danger) => async () => {
      if (!await this.confirm(title, body, label, danger)) return;
      if (await this.act("update_start", {kind, confirm: true}, "Started")) { this.job = {state: "running", description: title, log: ""}; this.lastState = "running"; this.draw(); this.refresh(); }
    };
    this.$("#light").onclick = start("clean-light", "Free caches", "Clears package, snap, journal and user caches plus Docker build cache and dangling images. Nothing in use is touched.", "Clean", false);
    this.$("#deep").onclick = start("clean-deep", "Deep clean", "Also removes every unused Docker image and stopped (non-managed) container, and trims Home Assistant automatic backups to the newest 3. Removed images are pulled again if needed.", "Deep clean", true);
    this.$("#repack").onclick = async () => {
      if (!await this.confirm("Purge and repack the recorder?", "Applies the configured retention and rewrites the database file to reclaim space. This can take several minutes and needs free space about the size of the database while it runs.", "Start", true)) return;
      try { await this._hass.callService("recorder", "purge", {repack: true}); this.toast("Recorder purge started"); } catch (e) { this.fail(e); }
    };
    const log = this.$("#log"); if (log) log.scrollTop = log.scrollHeight;
  }
}
if (!customElements.get("opiha-storage-tab")) customElements.define("opiha-storage-tab", StorageTab);
