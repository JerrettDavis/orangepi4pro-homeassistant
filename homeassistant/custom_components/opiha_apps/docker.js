import {Tab, esc} from "./common.js";

class DockerTab extends Tab {
  interval = 10000;
  section = "containers"; data = null; images = null;
  async load() {
    if (this.section === "containers") this.data = await this.ws("docker", {stats: true});
    else this.images = await this.ws("images");
  }
  view() {
    const nav = `<div class="seg"><button class="${this.section === "containers" ? "active" : ""}" data-section="containers">Containers</button><button class="${this.section === "images" ? "active" : ""}" data-section="images">Images &amp; volumes</button></div>`;
    return nav + (this.section === "containers" ? this.containersView() : this.imagesView());
  }
  containersView() {
    const d = this.data; if (!d) return `<div class="empty">Reading Docker…</div>`;
    const s = d.summary;
    return `<div class="chips"><span class="chip">Engine ${esc(s.version)}</span><span class="chip good">${s.running} running</span><span class="chip">${s.stopped} stopped</span><span class="chip">${s.images} images</span><span class="chip">${esc(s.driver)}</span></div>
      <div class="wrap"><table><thead><tr><th>Container</th><th>State</th><th>CPU</th><th>Memory</th><th>Image</th><th class="actions"></th></tr></thead><tbody>
      ${d.containers.map(c => `<tr><td><strong>${esc(c.name)}</strong><div class="muted" style="font-size:12px">${esc(c.status)}${c.managed ? " · managed by Orange Pi" : c.compose ? " · compose " + esc(c.compose) : ""}</div></td>
        <td><span class="badge ${c.state === "running" ? "good" : c.state === "exited" || c.state === "dead" ? "bad" : "warn"}">${esc(c.state)}</span></td><td>${esc(c.cpu || "–")}</td><td>${esc((c.memory || "–").split(" / ")[0])}</td><td class="muted" style="overflow-wrap:anywhere">${esc(c.image)}</td>
        <td class="actions">${c.state === "running" ? `<button class="small" data-c="${esc(c.id)}" data-act="stop">Stop</button><button class="small" data-c="${esc(c.id)}" data-act="restart">Restart</button>` : `<button class="small" data-c="${esc(c.id)}" data-act="start">Start</button>`}
          <button class="small" data-c="${esc(c.id)}" data-act="logs" data-name="${esc(c.name)}">Logs</button>${c.managed ? "" : `<button class="small danger" data-c="${esc(c.id)}" data-act="remove" data-name="${esc(c.name)}">Remove</button>`}</td></tr>`).join("")}</tbody></table></div>
      ${d.containers.length ? "" : `<div class="empty">No containers.</div>`}
      <p class="muted" style="margin-top:14px">Apps installed from the Apps tab and the Home Assistant stack are managed there; removing them here is blocked so their state stays consistent. For anything else use the Terminal tab.</p>`;
  }
  imagesView() {
    const d = this.images; if (!d) return `<div class="empty">Reading images…</div>`;
    return `<div class="row" style="margin-bottom:12px"><h2 class="grow" style="margin:0">Images</h2><button id="prune">Remove dangling images…</button></div>
      <div class="wrap"><table><thead><tr><th>Repository</th><th>Tag</th><th>Size</th><th>Created</th><th class="actions"></th></tr></thead><tbody>
      ${d.images.map(i => `<tr><td>${esc(i.repository)} ${i.in_use ? `<span class="badge good">in use</span>` : ""}</td><td>${esc(i.tag)}</td><td>${esc(i.size)}</td><td class="muted">${esc(i.created)}</td><td class="actions">${i.in_use ? "" : `<button class="small danger" data-image="${esc(i.id)}" data-name="${esc(i.repository)}:${esc(i.tag)}">Remove</button>`}</td></tr>`).join("")}</tbody></table></div>
      <div class="cards" style="margin-top:16px"><section class="card"><h3>Volumes</h3>${d.volumes.length ? d.volumes.map(v => `<div><code>${esc(v)}</code></div>`).join("") : `<span class="muted">None</span>`}</section>
      <section class="card"><h3>Networks</h3>${d.networks.map(v => `<div><code>${esc(v)}</code></div>`).join("")}</section></div>`;
  }
  bind() {
    this.$$("[data-section]").forEach(b => b.onclick = () => { this.section = b.dataset.section; this.draw(); this.refresh(); });
    this.$$("[data-c]").forEach(b => b.onclick = () => this.container(b.dataset.c, b.dataset.act, b.dataset.name));
    this.$$("[data-image]").forEach(b => b.onclick = async () => {
      if (!await this.confirm("Remove image?", `Delete <code>${esc(b.dataset.name)}</code> from this host. It can be pulled again later.`, "Remove", true)) return;
      if (await this.act("image", {id: b.dataset.image, action: "remove", confirm: true}, "Image removed")) this.refresh();
    });
    const prune = this.$("#prune");
    if (prune) prune.onclick = async () => {
      if (!await this.confirm("Remove dangling images?", "Untagged leftovers from earlier pulls are deleted. Images that containers use are kept.", "Remove", true)) return;
      const r = await this.act("docker_prune", {confirm: true}); if (r) { this.modal("Cleanup finished", `<pre>${esc(r.output)}</pre><div class="buttons"><button data-close>Close</button></div>`); this.refresh(); }
    };
  }
  async container(id, action, name) {
    if (action === "logs") {
      try { const r = await this.ws("container_logs", {id, lines: 300}); this.modal("Logs · " + name, `<p class="muted">Logs can contain private data.</p><pre>${esc(r.logs)}</pre><div class="buttons"><button data-close>Close</button></div>`); } catch (e) { this.fail(e); }
      return;
    }
    const risky = ["stop", "restart", "remove"].includes(action);
    if (risky && !await this.confirm(`${action[0].toUpperCase() + action.slice(1)} container?`, action === "remove" ? `<code>${esc(name)}</code> is deleted. Data in bind mounts and named volumes is kept.` : `This ${esc(action)}s <code>${esc(name || id)}</code>.`, action[0].toUpperCase() + action.slice(1), action !== "restart")) return;
    if (await this.act("container", {id, action, confirm: risky ? true : undefined}, `${action}: done`)) this.refresh();
  }
}
if (!customElements.get("opiha-docker-tab")) customElements.define("opiha-docker-tab", DockerTab);
