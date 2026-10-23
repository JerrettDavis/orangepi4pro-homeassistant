import {Tab, esc} from "./common.js";

const MODES = {
  kiosk: ["Kiosk", "Home Assistant fills the screen in a locked-down browser."],
  desktop: ["Desktop", "The full XFCE desktop is showing."],
  "no-session": ["No desktop session", "Nobody is logged in to the desktop on this host."],
  unavailable: ["Unavailable", "The kiosk account's session manager could not be reached."],
};
const UNIT_LABELS = {kiosk: "Kiosk browser", controls: "Touch controls", keyboard: "On-screen keyboard"};

class DesktopTab extends Tab {
  interval = 5000;
  info = null;
  async load() { this.info = await this.ws("desktop"); }
  view() {
    const i = this.info; if (!i) return `<div class="empty">Reading the display session…</div>`;
    const [title, text] = MODES[i.mode] || [i.mode, ""];
    return `<div class="cards">
      <section class="card"><div class="label">Right now</div><div class="big">${esc(title)}</div><p class="muted">${esc(text)}${i.detail ? " " + esc(i.detail) : ""}</p>
        <div class="row">${i.mode === "kiosk"
          ? `<button id="desktop" class="primary">Switch to desktop…</button>`
          : `<button id="kiosk" class="primary" ${i.mode === "no-session" || i.mode === "unavailable" ? "disabled" : ""}>Return to kiosk</button>`}</div></section>
      <section class="card"><div class="label">At boot</div><div class="big">${i.boot === "desktop" ? "Desktop" : "Kiosk"}</div><p class="muted">What the screen shows after the next reboot or login.</p>
        <div class="row"><button id="boot-kiosk" class="${i.boot === "kiosk" ? "active" : ""}">Boot into kiosk</button><button id="boot-desktop" class="${i.boot === "desktop" ? "active" : ""}">Boot into desktop</button></div></section>
      <section class="card"><div class="label">Display</div><div class="big">Screen</div><p class="muted">Blank the panel immediately. A touch or key press wakes it.</p><div class="row"><button id="screen-off">Screen off</button><button id="screen-on">Wake</button></div></section>
    </div>
    <h2>Kiosk components</h2>
    <div class="wrap"><table><thead><tr><th>Component</th><th>State</th><th>Starts at login</th></tr></thead><tbody>
      ${Object.entries(UNIT_LABELS).map(([k, label]) => { const u = i.units[k] || {}; return `<tr><td><strong>${label}</strong></td><td><span class="badge ${u.active === "active" ? "good" : u.active === "failed" ? "bad" : ""}">${esc(u.active || "unknown")}</span></td><td>${esc(u.enabled || "–")}</td></tr>`; }).join("")}
    </tbody></table></div>
    <div class="notice" style="margin-top:18px"><strong>Getting back.</strong> In desktop mode, open <em>Return to Home Assistant kiosk</em> from the applications menu, or press <em>Return to kiosk</em> here from any other browser. Starting the kiosk also makes it the boot default again. The kiosk account must be a Home Assistant administrator to open this panel.</div>`;
  }
  bind() {
    if (!this.info) return;
    const set = (data, ok) => async () => { if (await this.act("desktop_mode", data, ok)) setTimeout(() => this.refresh(), 2500); };
    const desktop = this.$("#desktop"), kiosk = this.$("#kiosk");
    if (desktop) desktop.onclick = async () => { if (await this.confirm("Switch to the desktop?", "The full-screen browser and touch strip close in a couple of seconds, revealing the XFCE desktop. This browser tab ends if it is the kiosk itself.", "Switch to desktop")) set({mode: "desktop", confirm: true}, "Switching to desktop")(); };
    if (kiosk) kiosk.onclick = set({mode: "kiosk"}, "Starting the kiosk");
    this.$("#boot-kiosk").onclick = set({boot: "kiosk"}, "Next boot: kiosk");
    this.$("#boot-desktop").onclick = set({boot: "desktop"}, "Next boot: desktop");
    this.$("#screen-off").onclick = () => this.act("display", {action: "off"}, "Screen off");
    this.$("#screen-on").onclick = () => this.act("display", {action: "on"}, "Screen on");
  }
}
if (!customElements.get("opiha-desktop-tab")) customElements.define("opiha-desktop-tab", DesktopTab);
