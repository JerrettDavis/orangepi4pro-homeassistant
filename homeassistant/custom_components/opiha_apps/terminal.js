import {Tab, esc} from "./common.js";

const BASE = "/api/opiha_apps/";
let xtermReady = null;
function loadScript(name) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script"); s.src = BASE + name; s.onload = resolve; s.onerror = () => reject(new Error("Could not load " + name));
    document.head.append(s);
  });
}
function loadXterm() {
  if (window.Terminal && window.FitAddon) return Promise.resolve();
  xtermReady ??= loadScript("xterm.js").then(() => loadScript("xterm-addon-fit.js")).catch(e => { xtermReady = null; throw e; });
  return xtermReady;
}
const decode = (b64) => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const encode = (text) => { const b = new TextEncoder().encode(text); let s = ""; for (const x of b) s += String.fromCharCode(x); return btoa(s); };

const KEYS = [["Esc", "\x1b"], ["Tab", "\t"], ["Ctrl+C", "\x03"], ["Ctrl+D", "\x04"], ["Ctrl+Z", "\x1a"], ["↑", "\x1b[A"], ["↓", "\x1b[B"], ["←", "\x1b[D"], ["→", "\x1b[C"], ["Home", "\x1b[H"], ["End", "\x1b[F"], ["PgUp", "\x1b[5~"], ["PgDn", "\x1b[6~"], ["|", "|"], ["~", "~"], ["/", "/"], ["-", "-"]];

class TerminalTab extends Tab {
  fontSize = 14; sid = null; cursor = 0; state = "idle"; message = "";
  extraCss() {
    return `<link rel="stylesheet" href="${BASE}xterm.css"><style>
      main{max-width:none;padding:12px 16px;display:flex;flex-direction:column;height:calc(100vh - 118px);min-height:260px}
      .bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;align-items:center}.bar button{min-width:44px}
      #screen{flex:1;min-height:0;background:#0d1117;border-radius:10px;padding:8px;overflow:hidden}
      .xterm{height:100%}.xterm-viewport{overflow-y:auto!important}
      .state{padding:30px;text-align:center}
    </style>`;
  }
  set active(value) { this.visible = value; if (value) setTimeout(() => this.fit(), 50); }
  get active() { return this.visible; }
  begin() { if (this.started) return; this.started = true; this.draw(); this.start(); }
  stop() { this.running = false; if (this.resizeObserver) this.resizeObserver.disconnect(); if (this.sid) this.ws("term_close", {id: this.sid}).catch(() => {}); this.sid = null; this.term?.dispose(); this.term = null; }
  view() {
    if (this.state === "off") return `<div class="card state"><h2>The host terminal is off</h2><p class="muted">A shell on the host is the strongest control this panel offers, so it is opt-in. Enable it once from an existing shell or SSH session:</p><p><code>sudo python3 /opt/orangepi-apps/current/bin/opiha-apps host-terminal on</code><br><code>sudo systemctl restart orangepi-apps.service</code></p><button id="retry" class="primary">Check again</button></div>`;
    return `<div class="bar">${KEYS.map(([label, seq], i) => `<button class="small" data-key="${i}" aria-label="Send ${esc(label)}">${esc(label)}</button>`).join("")}
      <span class="grow"></span><button class="small" id="smaller" aria-label="Smaller text">A−</button><button class="small" id="larger" aria-label="Larger text">A+</button><button class="small" id="reset">New session</button></div>
      ${this.message ? `<div class="error">${esc(this.message)}</div>` : ""}<div id="screen" role="application" aria-label="Host terminal"></div>`;
  }
  bind() {
    const retry = this.$("#retry"); if (retry) retry.onclick = () => this.start();
    if (this.state === "off") return;
    this.$$("[data-key]").forEach(b => b.onclick = () => { this.send(KEYS[b.dataset.key][1]); this.term?.focus(); });
    this.$("#larger").onclick = () => this.zoom(1); this.$("#smaller").onclick = () => this.zoom(-1);
    this.$("#reset").onclick = () => this.start(true);
    if (this.term) { const screen = this.$("#screen"); if (screen && this.term.element && !screen.contains(this.term.element)) { screen.append(this.term.element); this.fit(); } }
  }
  zoom(step) { this.fontSize = Math.min(28, Math.max(9, this.fontSize + step)); if (this.term) { this.term.options.fontSize = this.fontSize; this.fit(); } }
  fit() { try { this.fitAddon?.fit(); } catch {} }
  async start(fresh = false) {
    this.running = false;
    if (fresh && this.sid) { try { await this.ws("term_close", {id: this.sid}); } catch {} }
    this.sid = null; this.message = ""; this.cursor = 0; this.term?.dispose(); this.term = null;
    try { await loadXterm(); } catch (e) { this.message = e.message; this.draw(); return; }
    this.state = "ready"; this.draw();
    const term = this.term = new window.Terminal({cursorBlink: true, fontSize: this.fontSize, fontFamily: "ui-monospace,Menlo,Consolas,monospace", scrollback: 5000, theme: {background: "#0d1117"}});
    this.fitAddon = new window.FitAddon.FitAddon(); term.loadAddon(this.fitAddon);
    term.open(this.$("#screen")); this.fit();
    try { const r = await this.ws("term_open", {rows: term.rows, cols: term.cols}); this.sid = r.id; }
    catch (e) {
      this.term.dispose(); this.term = null;
      if (/terminal is off/i.test(e.message)) { this.state = "off"; } else { this.message = e.message; }
      this.draw(); return;
    }
    term.onData(data => this.send(data));
    this.resizeObserver?.disconnect(); this.resizeObserver = new ResizeObserver(() => this.fit()); this.resizeObserver.observe(this.$("#screen"));
    term.onResize(({rows, cols}) => { this.pendingSize = {rows, cols}; this.chain(() => this.io({}, 0)); });
    this.running = true; this.writing = Promise.resolve(); this.poll(this.sid);
    term.focus();
  }
  chain(task) { this.writing = (this.writing || Promise.resolve()).then(task).catch(() => {}); }
  send(data) { if (this.sid) this.chain(() => this.io({input: encode(data)}, 0)); }
  async io(extra, wait) {
    const id = this.sid; if (!id) return;
    const body = {id, cursor: this.cursor, wait, ...extra};
    if (this.pendingSize) { Object.assign(body, this.pendingSize); this.pendingSize = null; }
    const r = await this.ws("term_io", body);
    if (id === this.sid) this.apply(r);
    return r;
  }
  apply(r) {
    const bytes = decode(r.data), skip = Math.max(0, this.cursor - r.from);
    if (skip < bytes.length) this.term?.write(bytes.subarray(skip));
    this.cursor = Math.max(this.cursor, r.cursor);
    if (r.exited && this.running) { this.running = false; this.term?.write("\r\n\x1b[33m[session ended — press New session]\x1b[0m\r\n"); }
  }
  async poll(id) {
    let failures = 0;
    while (this.running && this.sid === id && this.isConnected) {
      try { await this.io({}, 1); failures = 0; }
      catch (e) {
        if (/ended|off/i.test(e.message)) { this.running = false; this.term?.write(`\r\n\x1b[33m[${e.message}]\x1b[0m\r\n`); return; }
        if (++failures > 5) { this.running = false; this.term?.write("\r\n\x1b[31m[connection lost — press New session]\x1b[0m\r\n"); return; }
        await new Promise(r => setTimeout(r, 1000));
      }
    }
  }
}
if (!customElements.get("opiha-terminal-tab")) customElements.define("opiha-terminal-tab", TerminalTab);
