/* Add-ons tab: Home Assistant add-on repositories, install planning and lifecycle. Third-party code, so every
   install shows what it can do and needs each privilege approved before a plan can be reviewed. */
import {Tab, esc} from "./common.js";

const STATUS = {works: ["good", "Works"], reduced: ["warn", "Reduced"], unsupported: ["bad", "Unsupported"], invalid: ["bad", "Invalid"]};
const badge = (status) => `<span class="badge ${STATUS[status]?.[0] || ""}">${STATUS[status]?.[1] || esc(status)}</span>`;

/* --- options form generated from an add-on `schema` ---------------------------------------------- */
function parseRule(rule) {
  const optional = rule.endsWith("?"), r = rule.replace(/\?$/, ""), open = r.indexOf("(");
  return {optional, base: open < 0 ? r : r.slice(0, open), arg: open < 0 ? "" : r.slice(open + 1, -1)};
}
function field(name, rule, value, path) {
  const id = `f:${path}`;
  if (typeof rule !== "string") {
    return `<label>${esc(name)} <small>(structured: edit as JSON)</small><textarea data-json="${esc(path)}" rows="4" style="width:100%;font:12px monospace">${esc(JSON.stringify(value ?? (Array.isArray(rule) ? [] : {}), null, 2))}</textarea></label>`;
  }
  const {optional, base, arg} = parseRule(rule);
  const req = optional ? "" : " required", data = `data-path="${esc(path)}" data-kind="${esc(base)}" data-optional="${optional}"`;
  if (base === "bool") return `<label class="check"><input type="checkbox" ${data} ${value ? "checked" : ""}> ${esc(name)}</label>`;
  if (base === "list") return `<label>${esc(name)}<select ${data}>${optional ? "<option value=''></option>" : ""}${arg.split("|").map(o => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
  if (base === "int" || base === "float" || base === "port") return `<label>${esc(name)}<input type="number" ${base === "float" ? 'step="any"' : ""} ${data} value="${esc(value ?? "")}"${req}></label>`;
  return `<label>${esc(name)}<input type="${base === "password" ? "password" : "text"}" ${data} value="${esc(value ?? "")}" autocomplete="off"${req}></label>`;
}
function schemaForm(schema, values, prefix = "") {
  return Object.entries(schema || {}).map(([k, rule]) => field(k, rule, (values || {})[k], prefix + k)).join("");
}
function collect(root, schema) {
  const out = {};
  const put = (path, value) => { const keys = path.split("."); let o = out; keys.slice(0, -1).forEach(k => o = o[k] ??= {}); o[keys.at(-1)] = value; };
  root.querySelectorAll("[data-path]").forEach(el => {
    const kind = el.dataset.kind, optional = el.dataset.optional === "true";
    if (kind === "bool") return put(el.dataset.path, el.checked);
    if (el.value === "") { if (!optional) put(el.dataset.path, ""); return; }
    put(el.dataset.path, ["int", "float", "port"].includes(kind) ? Number(el.value) : el.value);
  });
  root.querySelectorAll("[data-json]").forEach(el => put(el.dataset.json, JSON.parse(el.value || "null")));
  return out;
}

class OpihaStoreTab extends Tab {
  interval = 12000;
  constructor() {
    super(); this.repos = []; this.suggested = []; this.token = false; this.repo = null; this.rows = []; this.search = "";
    this.installed = []; this.job = null; this.loadingRows = false;
  }
  extraCss() {
    return `<style>label{display:block;margin-bottom:12px}label.check{display:flex;gap:8px;align-items:center}input:not([type=checkbox]),select,textarea{display:block;width:100%;margin-top:4px}
      .list{background:var(--card);border:1px solid var(--line);border-radius:10px}.item{display:flex;gap:12px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}.item:last-child{border-bottom:0}
      .item .grow small{display:block;color:var(--muted)}ul.plain{margin:6px 0 12px;padding-left:20px}.priv{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin-bottom:8px}.priv.high{border-color:var(--bad)}
      section{margin-bottom:26px}h2 small{font-weight:400;color:var(--muted);font-size:12px;margin-left:8px}</style>`;
  }
  stop() { clearTimeout(this.followTimer); }
  store(operation, data = {}) { return this._hass.callWS({type: "opiha_apps/store", operation, data}); }
  api(operation, data = {}) { return this._hass.callWS({type: "opiha_apps/request", operation, data}); }

  async load() {
    const [repos, overview] = await Promise.all([this.store("repos"), this.api("overview")]);
    this.repos = repos.repositories; this.suggested = repos.suggested; this.token = repos.ha_token_configured;
    this.installed = overview.apps.filter(a => a.kind === "addon" && (a.installed || a.data_retained)); this.job = overview.active_job; this.shim = overview.shim;
    if (!this.repo && this.repos.length) this.pick(this.repos[0].id, false);
    if (this.repo && !this.repos.some(r => r.id === this.repo)) { this.repo = null; this.rows = []; }
  }
  async pick(id, redraw = true) {
    this.repo = id; this.rows = []; this.loadingRows = true; if (redraw) this.draw();
    try { this.rows = (await this.store("repo_addons", {id})).addons; } catch (e) { this.fail(e); }
    this.loadingRows = false; this.draw();
  }

  view() {
    const filtered = this.rows.filter(r => `${r.manifest?.name || r.folder} ${r.manifest?.description || ""}`.toLowerCase().includes(this.search.toLowerCase()));
    const shimBad = this.shim && this.installed.length > 0 && !(this.shim.listening && this.shim.redirect);
    return `${shimBad ? `<div class="error" role="alert">The add-on API (http://supervisor/) is not available: ${esc(this.shim.error || "starting")}. Add-ons that call it will fail until this clears.</div>` : ""}${this.job ? `<div class="notice" role="status">${esc(this.job.app)} · ${esc(this.job.stage)}</div>` : ""}
    <div class="notice warn">Add-ons are third-party software from repositories <em>you</em> add. This panel runs them natively in Docker with the options and access you approve. It is not the Home Assistant Supervisor: some add-ons run with reduced capability and some cannot run at all, which is stated before you install.</div>
    <section><h2>Installed add-ons</h2>${this.installed.length ? `<div class="list">${this.installed.map(a => this.installedRow(a)).join("")}</div>` : `<p class="muted">None yet. Add a repository below and install one.</p>`}</section>
    <section><h2>Repositories</h2><div class="list">${this.repos.map(r => `<div class="item"><div class="grow"><strong>${esc(r.name)}</strong><small>${esc(r.url)}</small></div>
        <button class="small" data-pick="${r.id}" ${this.repo === r.id ? "disabled" : ""}>Browse</button><button class="small" data-refresh="${r.id}">Update</button><button class="small danger" data-remove="${r.id}">Remove</button></div>`).join("") || `<div class="item muted">No repositories added.</div>`}</div>
      <form id="addrepo" class="row" style="margin-top:12px"><input class="grow" name="url" placeholder="https://github.com/owner/repository" required pattern="https://.+"><button class="primary">Add repository</button></form>
      <div class="row" style="margin-top:8px">${this.suggested.filter(s => !this.repos.some(r => r.url === s.url)).map(s => `<button class="small" data-suggest="${esc(s.url)}" title="${esc(s.url)}">+ ${esc(s.name)}</button>`).join("")}</div></section>
    ${this.repo ? `<section><h2>${esc(this.repos.find(r => r.id === this.repo)?.name || "Repository")} <small>${filtered.length} of ${this.rows.length}</small></h2>
      <input id="search" type="search" placeholder="Find an add-on" value="${esc(this.search)}" style="margin-bottom:12px;width:100%">
      <div class="list">${this.loadingRows ? `<div class="item muted">Reading repository…</div>` : filtered.map(r => this.addonRow(r)).join("") || `<div class="item muted">No matching add-ons.</div>`}</div></section>` : ""}
    <section><h2>Home Assistant access for add-ons</h2><p class="muted">Add-ons that declare they use the Home Assistant API reach it through this host. They need a long-lived access token you create in your HA profile; it is stored only on the host, readable by the manager.
      ${this.token ? `<strong>A token is configured.</strong>` : "<strong>No token is configured, so those requests are refused.</strong>"}</p>
      <form id="token" class="row"><input class="grow" type="password" name="token" placeholder="Long-lived access token" autocomplete="off" required minlength="20"><button>${this.token ? "Replace token" : "Save token"}</button></form></section>`;
  }
  installedRow(a) {
    const busy = this.busy || !!this.job;
    const b = (action, label, cls = "") => `<button class="small ${cls}" data-act="${action}" data-app="${a.id}" ${busy ? "disabled" : ""}>${label}</button>`;
    const running = a.state === "running";
    return `<div class="item"><div class="grow"><strong>${esc(a.name)}</strong> <span class="badge ${running ? "good" : ""}">${esc(a.state.replaceAll("_", " "))}</span><small>${esc(a.options?.version || "")} · ${esc(a.manifest?.slug || "")}</small></div>
      ${a.installed ? (running ? (a.ingress ? b("open", "Open", "primary") : "") + b("stop", "Stop") + b("restart", "Restart") : b("start", "Start", "primary")) + b("configure", "Configure") + b("logs", "Logs") + b("remove", "Remove", "danger")
        : `<span class="muted">Removed, data kept</span>`}</div>`;
  }
  addonRow(r) {
    if (r.error) return `<div class="item"><div class="grow"><strong>${esc(r.folder)}</strong><small>${esc(r.error)}</small></div>${badge("invalid")}</div>`;
    const m = r.manifest, status = r.report.status, installed = this.installed.find(a => a.manifest?.slug === m.slug && a.repo === r.repository);
    return `<div class="item"><div class="grow"><strong>${esc(m.name)}</strong> <span class="muted">${esc(m.version)}</span><small>${esc(m.description)}</small></div>${badge(status)}
      <button class="small ${status === "unsupported" ? "" : "primary"}" data-details="${esc(r.folder)}">${installed ? (installed.options.version === m.version ? "Reinstall" : "Update") : "Install"}</button></div>`;
  }
  bind() {
    this.$("#addrepo")?.addEventListener("submit", async e => { e.preventDefault(); await this.addRepo(e.currentTarget.elements.url.value); });
    this.$("#token")?.addEventListener("submit", async e => { e.preventDefault(); const t = e.currentTarget.elements.token.value; try { await this.store("ha_token", {token: t}); this.toast("Token saved"); this.refresh(); } catch (x) { this.fail(x); } });
    this.$("#search")?.addEventListener("input", e => { this.search = e.target.value; const p = e.target.selectionStart; this.draw(); const i = this.$("#search"); i.focus(); try { i.setSelectionRange(p, p); } catch {} });
    this.$$("[data-pick]").forEach(b => b.onclick = () => this.pick(b.dataset.pick));
    this.$$("[data-suggest]").forEach(b => b.onclick = () => this.addRepo(b.dataset.suggest));
    this.$$("[data-refresh]").forEach(b => b.onclick = async () => { b.disabled = true; this.toast("Downloading…"); try { await this.store("repo_refresh", {id: b.dataset.refresh}); if (this.repo === b.dataset.refresh) await this.pick(this.repo); this.toast("Repository updated"); } catch (e) { this.fail(e); } this.refresh(); });
    this.$$("[data-remove]").forEach(b => b.onclick = async () => { if (await this.confirm("Remove repository?", "Installed add-ons keep running; they just stop appearing in this list.", "Remove", true)) { try { await this.store("repo_remove", {id: b.dataset.remove}); } catch (e) { this.fail(e); } this.refresh(); } });
    this.$$("[data-details]").forEach(b => b.onclick = () => this.details(b.dataset.details));
    this.$$("[data-act]").forEach(b => b.onclick = () => this.lifecycle(b.dataset.app, b.dataset.act));
  }
  async addRepo(url) {
    this.toast("Downloading repository…");
    try { const r = await this.store("repo_add", {url}); this.toast("Added " + r.name); await this.refresh(); await this.pick(r.id); } catch (e) { this.fail(e); }
  }

  /* --- install / update ------------------------------------------------------------------------ */
  details(folder) {
    const r = this.rows.find(x => x.folder === folder); if (!r || r.error) return;
    const m = r.manifest, rep = r.report, blocked = rep.status === "unsupported";
    const installed = this.installed.find(a => a.manifest?.slug === m.slug && a.repo === r.repository);
    const previous = installed?.options;
    const ports = m.ports.filter(p => p.default_host !== null);
    const list = (items) => items.length ? `<ul class="plain">${items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : "";
    const d = this.modal(`${installed ? "Update" : "Install"} ${m.name} ${m.version}`, `<p>${esc(m.description)}</p>
      <p>${badge(rep.status)} ${r.has_dockerfile && !m.image ? "Built on this device from its Dockerfile (needs ≥ 4 GiB free storage and several minutes)." : ""}</p>
      ${rep.blocked.length ? `<h3>Cannot run here</h3>${list(rep.blocked)}` : ""}${rep.reduced.length ? `<h3>Reduced capability</h3>${list(rep.reduced)}` : ""}${rep.notes?.length ? `<p class="muted">${rep.notes.map(esc).join(" · ")}</p>` : ""}
      <form>${rep.privileges.length ? `<h3>Access this add-on asks for</h3>${rep.privileges.map(p => `<label class="priv ${p.risk}"><input type="checkbox" data-grant="${esc(p.id)}" ${previous?.grants?.includes(p.id) ? "checked" : ""}> ${esc(p.label)} <span class="badge ${p.risk === "high" ? "bad" : "warn"}">${esc(p.risk)}</span></label>`).join("")}` : ""}
      ${m.schema && Object.keys(m.schema).length ? `<h3>Options</h3>${schemaForm(m.schema, previous?.config ?? m.options)}` : ""}
      <div class="row"><label class="grow">Memory ceiling (MiB)<input name="memory_mib" type="number" min="128" max="32768" value="${previous?.memory_mib ?? 512}" required></label>
      <label class="check"><input type="checkbox" name="autostart" ${previous?.autostart ? "checked" : ""}> Start on host boot (after its first explicit start)</label></div>
      ${ports.length ? `<h3>Network ports</h3><label class="check"><input type="checkbox" name="lan" ${previous?.lan ? "checked" : ""}> Make these ports reachable from my LAN (otherwise they stay on this host)</label>
        <div class="row">${ports.map(p => { const k = `${p.container}/${p.protocol}`; return `<label>${esc(k)} → host port<input type="number" data-port="${esc(k)}" min="1" max="65535" value="${previous?.host_ports?.[k] ?? 20000 + (p.default_host % 10000)}"></label>`; }).join("")}</div>` : ""}
      <div class="buttons"><button type="button" data-close>Cancel</button><button class="primary" id="review" ${blocked ? "disabled" : ""}>Review plan</button></div></form>`);
    const form = d.querySelector("form");
    const sync = () => { d.querySelector("#review").disabled = blocked || [...form.querySelectorAll("[data-grant]")].some(c => !c.checked); };
    form.querySelectorAll("[data-grant]").forEach(c => c.onchange = sync); sync();
    form.onsubmit = async e => {
      e.preventDefault();
      try {
        const options = {grants: [...form.querySelectorAll("[data-grant]")].filter(c => c.checked).map(c => c.dataset.grant),
          memory_mib: Number(form.elements.memory_mib.value), autostart: form.elements.autostart.checked,
          config: m.schema === false ? {} : collect(form, m.schema)};
        if (ports.length) {
          options.lan = form.elements.lan.checked;
          options.host_ports = Object.fromEntries([...form.querySelectorAll("[data-port]")].map(i => [i.dataset.port, Number(i.value)]));
        }
        d.close(); await this.review({repository: r.repository, folder, options}, `${installed ? "Update" : "Install"} ${m.name}`);
      } catch (x) { this.fail(x); }
    };
  }
  async review(request, title) {
    try {
      const plan = await this.store("addon_plan", request);
      this.showPlan(plan, title);
    } catch (e) { this.fail(e); }
  }
  showPlan(plan, title) {
    const li = (xs) => xs?.length ? `<ul class="plain">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    const d = this.modal(title || "Review operation", `<dl class="kv"><dt>Operation</dt><dd>${esc(plan.action)} ${esc(plan.app)}</dd><dt>Image</dt><dd><code>${esc(plan.image)}</code></dd>
      <dt>Memory</dt><dd>${esc(plan.options.memory_mib)} MiB ceiling</dd>${plan.builds_locally ? "<dt>Build</dt><dd>On this device from the repository's Dockerfile</dd>" : ""}
      ${plan.options.host_ports && Object.keys(plan.options.host_ports).length ? `<dt>Ports</dt><dd>${Object.entries(plan.options.host_ports).map(([k, v]) => `${esc(k)} → ${plan.options.lan ? "LAN" : "127.0.0.1"}:${esc(v)}`).join(", ")}</dd>` : ""}
      ${plan.privileges?.length ? `<dt>Access granted</dt><dd>${plan.privileges.map(p => esc(p.label)).join("<br>")}</dd>` : ""}</dl>
      <h3>Before you approve</h3>${li(plan.warnings)}${plan.report?.reduced?.length ? `<h3>Reduced capability</h3>${li(plan.report.reduced)}` : ""}
      <div class="buttons"><button data-close>Cancel</button><button class="primary" id="approve">Approve ${esc(plan.action)}</button></div>`);
    d.querySelector("#approve").onclick = async () => { d.close(); try { const job = await this.api("apply", {id: plan.id, confirm: true}); this.toast("Started"); this.follow(job.id); } catch (e) { this.fail(e); } };
  }
  async follow(id) {
    try {
      const j = await this.api("job", {id}); this.job = j.status === "queued" || j.status === "running" ? j : null; this.draw();
      if (this.job && this.isConnected) { this.followTimer = setTimeout(() => this.follow(id), 2000); return; }
      await this.refresh(); j.status === "succeeded" ? this.toast("Done") : this.fail(new Error(j.stage));
    } catch (e) { this.fail(e); }
  }

  /* --- lifecycle of installed add-ons ---------------------------------------------------------- */
  async lifecycle(slug, action) {
    const a = this.installed.find(x => x.id === slug); if (!a) return;
    try {
      if (action === "open") { this.dispatchEvent(new CustomEvent("opiha-navigate", {detail: {tab: "apps", open: slug}, bubbles: true, composed: true})); return; }
      if (action === "logs") { const r = await this.api("logs", {app: slug}); this.modal(`${a.name} logs`, `<p class="muted">Logs can contain private data.</p><pre>${esc(r.logs)}</pre><div class="buttons"><button data-close>Close</button></div>`); return; }
      if (action === "configure") return this.configure(a);
      const plan = await this.api("plan", {app: slug, action}); this.showPlan(plan, `${action[0].toUpperCase() + action.slice(1)} ${a.name}`);
    } catch (e) { this.fail(e); }
  }
  configure(a) {
    const m = a.manifest, o = a.options;
    if (m.schema === false || !m.schema || !Object.keys(m.schema).length) { this.toast("This add-on has no options"); return; }
    const d = this.modal(`${a.name} options`, `<form>${schemaForm(m.schema, o.config)}<p class="muted">Saved options are written to the add-on and it restarts if it is running.</p>
      <div class="buttons"><button type="button" data-close>Cancel</button><button class="primary">Review plan</button></div></form>`);
    d.querySelector("form").onsubmit = async e => {
      e.preventDefault();
      try { const config = collect(e.currentTarget, m.schema); d.close(); const plan = await this.api("plan", {app: a.id, action: "configure", options: {...o, config}}); this.showPlan(plan, `Apply ${a.name} options`); }
      catch (x) { this.fail(x); }
    };
  }
}
if (!customElements.get("opiha-store-tab")) customElements.define("opiha-store-tab", OpihaStoreTab);
