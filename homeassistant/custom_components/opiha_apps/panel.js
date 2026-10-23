/* Orange Pi panel shell: one sidebar entry, tabs for each area. Tab code loads on first use. */
const TABS = [
  {id: "overview", label: "Overview", icon: "mdi:view-dashboard-outline", tag: "opiha-overview-tab", module: "./overview.js"},
  {id: "host", label: "Host", icon: "mdi:server", tag: "opiha-host-tab", module: "./host.js"},
  {id: "docker", label: "Docker", icon: "mdi:docker", tag: "opiha-docker-tab", module: "./docker.js"},
  {id: "apps", label: "Apps", icon: "mdi:apps", tag: "opiha-apps-tab", module: "./apps.js"},
  {id: "updates", label: "Updates", icon: "mdi:update", tag: "opiha-updates-tab", module: "./updates.js"},
  {id: "terminal", label: "Terminal", icon: "mdi:console", tag: "opiha-terminal-tab", module: "./terminal.js"},
  {id: "desktop", label: "Desktop", icon: "mdi:monitor-dashboard", tag: "opiha-desktop-tab", module: "./desktop.js"},
];
const STORE = "opiha-panel-tab";
const remembered = () => { try { return localStorage.getItem(STORE); } catch { return null; } };
const remember = (id) => { try { localStorage.setItem(STORE, id); } catch {} };

class OrangePiPanel extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode: "open"}); this.elements = {}; this.current = null; this.built = false;
  }
  set hass(value) {
    this._hass = value;
    for (const el of Object.values(this.elements)) el.hass = value;
    if (this.isConnected && !this.built) this.build();
  }
  get hass() { return this._hass; }
  set narrow(value) { this._narrow = value; const m = this.shadowRoot.getElementById("menu"); if (m) m.hidden = !value; }
  connectedCallback() { if (this._hass && !this.built) this.build(); }
  disconnectedCallback() { this.built = false; this.elements = {}; this.current = null; }
  build() {
    this.built = true;
    if (this._hass?.user && !this._hass.user.is_admin) {
      this.shadowRoot.innerHTML = `<p style="padding:24px;color:var(--error-color,#b00020)">Administrator access is required.</p>`; return;
    }
    this.shadowRoot.innerHTML = `<style>
      :host{display:flex;flex-direction:column;height:100%;background:var(--primary-background-color,#f3f6fa);color:var(--primary-text-color,#172b41)}
      *{box-sizing:border-box}
      header{display:flex;align-items:center;gap:6px;padding:0 12px;background:var(--app-header-background-color,var(--card-background-color,#fff));border-bottom:1px solid var(--divider-color,#d9e1e8);min-height:56px;flex:none}
      h1{font-size:19px;font-weight:500;margin:0 14px 0 6px;white-space:nowrap}
      nav{display:flex;gap:2px;overflow-x:auto;flex:1;scrollbar-width:none}nav::-webkit-scrollbar{display:none}
      nav button,#menu{display:flex;align-items:center;gap:7px;border:0;background:transparent;color:var(--secondary-text-color,#64748b);font:inherit;font-size:14px;padding:0 14px;min-height:56px;cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap}
      nav button:hover{color:var(--primary-text-color,#172b41)}nav button[aria-selected=true]{color:var(--primary-color,#087f8c);border-bottom-color:var(--primary-color,#087f8c)}
      #menu{padding:0 8px;border:0}ha-icon{--mdc-icon-size:20px}
      #content{flex:1;min-height:0;overflow:auto}#content>*{display:block}#content>[hidden]{display:none}
      #content>opiha-apps-tab{height:100%}
      @media(max-width:760px){nav button span{display:none}nav button{padding:0 12px}h1{display:none}}
    </style>
    <header><button id="menu" aria-label="Open sidebar" ${this._narrow ? "" : "hidden"}><ha-icon icon="mdi:menu"></ha-icon></button><h1>Orange Pi</h1>
      <nav role="tablist">${TABS.map(t => `<button role="tab" data-tab="${t.id}" aria-selected="false" title="${t.label}"><ha-icon icon="${t.icon}"></ha-icon><span>${t.label}</span></button>`).join("")}</nav></header>
    <div id="content"></div>`;
    this.shadowRoot.getElementById("menu").onclick = () => this.dispatchEvent(new Event("hass-toggle-menu", {bubbles: true, composed: true}));
    this.shadowRoot.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => this.select(b.dataset.tab));
    const wanted = (location.hash || "").slice(1) || remembered();
    this.select(TABS.some(t => t.id === wanted) ? wanted : "overview");
  }
  async select(id) {
    const tab = TABS.find(t => t.id === id); if (!tab) return;
    this.current = id; remember(id);
    try { history.replaceState(history.state, "", "#" + id); } catch {}
    this.shadowRoot.querySelectorAll("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
    const content = this.shadowRoot.getElementById("content");
    if (!this.elements[id]) {
      try { await import(tab.module); } catch (e) { content.innerHTML = `<p style="padding:24px;color:var(--error-color,#b00020)">Could not load ${tab.label}: ${String(e.message || e).replace(/[<&]/g, "")}</p>`; return; }
      if (this.current !== id) return;
      const el = document.createElement(tab.tag); el.hidden = true; this.elements[id] = el; content.append(el); el.hass = this._hass;
    }
    for (const [key, el] of Object.entries(this.elements)) { el.hidden = key !== id; el.active = key === id; }
    content.querySelectorAll(":scope > p").forEach(p => p.remove());
  }
}
if (!customElements.get("opiha-apps-panel")) customElements.define("opiha-apps-panel", OrangePiPanel);
