/* Shared helpers and the Tab base class for the Orange Pi panel. Uses HA's authenticated WebSocket only. */
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, x => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));

export function bytes(n) {
  if (!Number.isFinite(n)) return "–";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]; let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}
export const rate = (n) => Number.isFinite(n) ? bytes(n) + "/s" : "–";
export function duration(seconds) {
  if (!Number.isFinite(seconds)) return "–";
  const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
export const pct = (n) => Number.isFinite(n) ? `${n.toFixed(n >= 100 ? 0 : 1)}%` : "–";

export function spark(values, max = 100, color = "var(--accent)") {
  if (values.length < 2) return `<svg class="spark" viewBox="0 0 100 24" preserveAspectRatio="none"></svg>`;
  const step = 100 / (values.length - 1);
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(23 - Math.min(1, Math.max(0, v / max)) * 22).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
export function meter(fraction, label = "") {
  const f = Number.isFinite(fraction) ? Math.min(1, Math.max(0, fraction)) : 0;
  const level = f > .9 ? "hot" : f > .75 ? "warm" : "";
  return `<div class="meter ${level}" role="meter" aria-valuenow="${Math.round(f * 100)}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(label)}"><i style="width:${(f * 100).toFixed(1)}%"></i></div>`;
}

export const CSS = `<style>
  :host{display:block;--accent:#087f8c;--line:var(--divider-color,#d9e1e8);--ink:var(--primary-text-color,#172b41);--muted:var(--secondary-text-color,#64748b);--card:var(--card-background-color,#fff);--bg:var(--primary-background-color,#f3f6fa);--soft:var(--secondary-background-color,#f8fafc);--bad:#c0392b;--warn:#b7791f;--good:#1f8a5b;color:var(--ink);font:14px/1.5 var(--paper-font-body1_-_font-family,Arial,sans-serif)}
  *{box-sizing:border-box}[hidden]{display:none!important}
  button,input,select,textarea{font:inherit;color:inherit}
  button{cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:8px 14px;min-height:38px}
  button:hover:not(:disabled){border-color:var(--accent)}button:disabled{cursor:default;opacity:.45}
  button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}button.danger{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,var(--line))}button.danger.primary{background:var(--bad);color:#fff;border-color:var(--bad)}
  button.small{padding:4px 10px;min-height:30px;font-size:13px}button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  input:not([type=checkbox]),select{border:1px solid var(--line);border-radius:7px;padding:8px 10px;background:var(--bg);min-height:38px}
  a{color:var(--accent)}code{font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;background:var(--soft);padding:1px 5px;border-radius:4px}
  main{max-width:1250px;margin:auto;padding:20px 24px 32px}
  h2{font-size:16px;margin:0 0 12px}h3{font-size:14px;margin:0 0 8px}
  .muted{color:var(--muted)}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.row.end{justify-content:flex-end}.grow{flex:1;min-width:140px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;min-width:0}
  .card .big{font-size:26px;font-weight:600;line-height:1.2}.card .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:13px}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}
  .meter{height:8px;border-radius:5px;background:var(--soft);border:1px solid var(--line);overflow:hidden;margin:8px 0 4px}.meter i{display:block;height:100%;background:var(--accent)}.meter.warm i{background:var(--warn)}.meter.hot i{background:var(--bad)}
  .spark{width:100%;height:34px;display:block;margin-top:6px}
  .chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}.chip{padding:5px 12px;border-radius:16px;border:1px solid var(--line);background:var(--card);font-size:13px}.chip.bad{border-color:var(--bad);color:var(--bad)}.chip.warn{border-color:var(--warn);color:var(--warn)}.chip.good{border-color:var(--good);color:var(--good)}
  .badge{font-size:11px;border-radius:12px;padding:2px 8px;background:var(--soft);color:var(--muted);white-space:nowrap}.badge.good{background:#e0f4ef;color:#155d51}.badge.bad{background:#fcebef;color:#822733}.badge.warn{background:#fdf1d8;color:#7a5412}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}th{font-size:12px;color:var(--muted);font-weight:600;background:var(--soft)}tr:last-child td{border-bottom:0}
  td.nowrap{white-space:nowrap}td.actions{text-align:right;white-space:nowrap}td.actions button{margin-left:4px}.wrap{overflow-x:auto}
  .seg{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
  .error{padding:14px 16px;background:#fcebef;color:#822733;border-radius:10px;margin-bottom:16px;white-space:pre-wrap}.notice{padding:12px 16px;border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;margin-bottom:16px;background:var(--card)}.notice.warn{border-left-color:var(--warn)}
  .empty{padding:36px;text-align:center;color:var(--muted)}
  pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;font:12px/1.55 ui-monospace,Menlo,Consolas,monospace;margin:0}
  dialog{border:1px solid var(--line);border-radius:14px;max-width:760px;width:calc(100% - 32px);max-height:88vh;padding:22px;background:var(--card);color:var(--ink)}dialog::backdrop{background:#13253680}dialog h2{margin:0 0 12px;font-size:18px}
  .buttons{display:flex;justify-content:flex-end;gap:10px;margin-top:18px;flex-wrap:wrap}
  .toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#172b41;color:#fff;padding:10px 18px;border-radius:10px;z-index:9;max-width:90vw}.toast.bad{background:var(--bad)}
  @media(max-width:650px){main{padding:14px}.card .big{font-size:22px}th:nth-child(n+4),td:nth-child(n+4){display:none}td.actions,th.actions{display:table-cell!important}}
</style>`;

/** Base class: shadow-root tab with polling, a confirm dialog and toasts. Subclasses implement view() and bind(). */
export class Tab extends HTMLElement {
  interval = 0;
  constructor() {
    super(); this.attachShadow({mode: "open"}); this.error = ""; this.started = false; this.visible = true; this.timer = null; this.busy = false;
    this.shadowRoot.innerHTML = CSS + this.extraCss() + `<main id="main"></main><dialog id="dialog"></dialog>`;
    this.main = this.shadowRoot.getElementById("main"); this.dialog = this.shadowRoot.getElementById("dialog");
  }
  extraCss() { return ""; }
  set hass(value) { this._hass = value; if (!this.started && this.isConnected) this.begin(); }
  get hass() { return this._hass; }
  set active(value) { this.visible = value; if (value && this.started) { this.refresh(); } }
  connectedCallback() { if (this._hass) this.begin(); }
  disconnectedCallback() { clearInterval(this.timer); this.started = false; this.stop(); }
  stop() {}
  begin() {
    if (this.started) return; this.started = true; this.draw();
    this.refresh();
    if (this.interval) this.timer = setInterval(() => { if (this.visible && !document.hidden && !this.dialog.open && !this.typing()) this.refresh(); }, this.interval);
  }
  typing() { const a = this.shadowRoot.activeElement; return !!a && ["INPUT", "SELECT", "TEXTAREA"].includes(a.tagName); }
  ws(operation, data = {}) { return this._hass.callWS({type: "opiha_apps/host", operation, data}); }
  async refresh() {
    if (this.refreshing) return; this.refreshing = true;
    try { await this.load(); this.error = ""; } catch (e) { this.error = e.message || String(e); }
    finally { this.refreshing = false; this.draw(); }
  }
  async load() {}
  view() { return ""; }
  bind() {}
  draw() {
    if (this.dialog.open && this.freeze) return;
    const scroller = this.parentElement, top = scroller ? scroller.scrollTop : 0;
    this.main.innerHTML = (this.error ? `<div class="error" role="alert">${esc(this.error)}</div>` : "") + this.view();
    this.bind(); if (scroller) scroller.scrollTop = top;
  }
  $(selector) { return this.shadowRoot.querySelector(selector); }
  $$(selector) { return [...this.shadowRoot.querySelectorAll(selector)]; }
  toast(message, bad = false) {
    const el = document.createElement("div"); el.className = "toast" + (bad ? " bad" : ""); el.textContent = message; el.setAttribute("role", "status");
    this.shadowRoot.append(el); setTimeout(() => el.remove(), bad ? 6000 : 3000);
  }
  fail(e) { this.toast(e.message || String(e), true); }
  modal(title, body) {
    this.dialog.innerHTML = `<h2>${esc(title)}</h2>${body}`; this.freeze = true;
    this.dialog.onclose = () => { this.freeze = false; this.dialog.innerHTML = ""; this.draw(); };
    this.dialog.querySelectorAll("[data-close]").forEach(b => b.onclick = () => this.dialog.close());
    if (!this.dialog.open) this.dialog.showModal(); return this.dialog;
  }
  confirm(title, message, label = "Confirm", danger = false) {
    return new Promise(resolve => {
      const d = this.modal(title, `<p>${message}</p><div class="buttons"><button data-close>Cancel</button><button id="ok" class="primary ${danger ? "danger" : ""}">${esc(label)}</button></div>`);
      let answered = false;
      d.querySelector("#ok").onclick = () => { answered = true; d.close(); };
      const previous = d.onclose; d.onclose = () => { previous(); resolve(answered); };
    });
  }
  /** Run a host operation with a progress toast; returns the result or undefined after showing the error. */
  async act(operation, data, success) {
    if (this.busy) return; this.busy = true;
    try { const r = await this.ws(operation, data); if (success) this.toast(success); return r; }
    catch (e) { this.fail(e); } finally { this.busy = false; }
  }
}
