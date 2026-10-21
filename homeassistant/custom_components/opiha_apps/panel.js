/* Native custom panel. Uses HA's authenticated WebSocket/API client, never a stored bearer token. */
const escapeHtml = (v) => String(v ?? "").replace(/[&<>"']/g, x => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));
const mib = (v) => Number.isFinite(v) ? `${(v / 1048576).toFixed(0)} MiB` : "Unavailable";
class OpihaAppsPanel extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:"open"}); this.state=null; this.busy=false; this.selected=null;
    this.filter="all"; this.search=""; this.timer=null; this.renewTimer=null; this.error="";
    this.onVisibility=()=>{if (!document.hidden && !this.selected) this.refresh();};
  }
  set hass(value) { this._hass=value; if (!this.started && this.isConnected) this.start(); }
  get hass() {return this._hass;}
  connectedCallback() { if(this._hass) this.start(); }
  disconnectedCallback() {clearInterval(this.timer);clearInterval(this.renewTimer);this.started=false;document.removeEventListener("visibilitychange",this.onVisibility);}
  start() {
    if(this.started)return; this.started=true;this.render();this.refresh();
    this.timer=setInterval(()=>{if(!document.hidden&&!this.selected&&!this.busy) this.refresh();},15000);
    document.addEventListener("visibilitychange",this.onVisibility);
  }
  async api(operation,data={}) {return this._hass.callWS({type:"opiha_apps/request",operation,data});}
  async refresh() {
    if(this.refreshing)return;this.refreshing=true;
    try{this.state=await this.api("overview");this.error="";}catch(e){this.error=e.message||String(e);}
    finally{this.refreshing=false;if(!this.selected&&!this.dialogOpen)this.render();}
  }
  css(){return `<style>
    :host{display:block;--accent:#087f8c;--line:var(--divider-color,#d9e1e8);--ink:var(--primary-text-color,#172b41);--muted:var(--secondary-text-color,#64748b);color:var(--ink);background:var(--primary-background-color,#f3f6fa);height:100%;overflow:auto;font:14px/1.5 var(--paper-font-body1_-_font-family,Arial,sans-serif)}
    *{box-sizing:border-box}button,input,select{font:inherit}button{cursor:pointer;border:1px solid var(--line);background:var(--card-background-color,#fff);color:var(--ink);border-radius:8px;padding:9px 14px}button:hover:not(:disabled){border-color:var(--accent)}button:disabled{cursor:default;opacity:.45}button.primary{background:var(--accent);color:white;border-color:var(--accent)}button.danger{color:#b33a42}button.link{border:0;padding:3px 6px;background:transparent}a{color:var(--accent)}
    header{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:22px 32px;background:var(--card-background-color,#fff);border-bottom:1px solid var(--line)}header h1{font-size:22px;line-height:1.2;margin:0}header p{color:var(--muted);margin:5px 0 0}ha-icon{color:var(--accent);width:24px;height:24px}main{max-width:1250px;margin:auto;padding:24px 32px}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 22px}.metric{padding:16px 20px;background:var(--card-background-color,#fff);border:1px solid var(--line);border-radius:12px}.metric strong{font-size:23px;display:block}.metric span{color:var(--muted)}.tools{display:flex;gap:10px;align-items:center;margin-bottom:18px;flex-wrap:wrap}.tools input{flex:1;min-width:180px}.tools .active{background:var(--accent);color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}.card{background:var(--card-background-color,#fff);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}.body{padding:20px;flex:1}.top{display:flex;align-items:center;gap:10px}.top h2{font-size:18px;margin:0;flex:1}.badge{font-size:11px;border-radius:12px;padding:3px 8px;background:var(--secondary-background-color,#eef3f8);color:var(--muted)}.badge.running{background:#e0f4ef;color:#155d51}.desc{min-height:44px;margin:16px 0 12px}.details{font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:8px}.actions{display:flex;gap:8px;flex-wrap:wrap;padding:13px 20px;background:var(--secondary-background-color,#f8fafc);border-top:1px solid var(--line)}.note{color:var(--muted);font-size:12px;margin-top:18px}.error{padding:16px;background:#fcebef;color:#822733;border-radius:10px;margin-bottom:18px}.notice{padding:14px;border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;margin-bottom:20px}.empty{padding:40px;text-align:center;color:var(--muted)}
    dialog{border:1px solid var(--line);border-radius:14px;max-width:700px;width:calc(100% - 32px);max-height:85vh;padding:24px;background:var(--card-background-color,#fff);color:var(--ink)}dialog::backdrop{background:#13253680}dialog h2{margin:0 0 16px}label{display:block;margin-bottom:14px}input:not([type=checkbox]),select{display:block;width:100%;border:1px solid var(--line);border-radius:7px;padding:9px;background:var(--primary-background-color,#f3f6fa);color:var(--ink);margin-top:4px}label small{display:block;color:var(--muted);margin-top:5px}.row{display:flex;gap:14px}.row>*{flex:1}.buttons{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:55vh;overflow:auto;background:var(--primary-background-color,#f3f6fa);border:1px solid var(--line);border-radius:8px;padding:14px;font:12px/1.6 monospace}.app-frame{width:100%;height:calc(100vh - 98px);border:0;background:white}.frame-head{padding:14px 24px}.frame-head small{color:var(--muted)}
    @media(max-width:650px){header{padding:18px;align-items:flex-start}header h1{font-size:20px}main{padding:18px}.summary{grid-template-columns:1fr}.metric{padding:12px 16px}.metric strong{display:inline;font-size:19px;margin-right:8px}.row{display:block}.grid{grid-template-columns:1fr}.details{flex-wrap:wrap}.tools button{padding:8px 10px}}
  </style>`;}
  render() {
    if(this.selected)return;
    if(this._hass?.user && !this._hass.user.is_admin){this.shadowRoot.innerHTML=this.css()+`<main><div class="error">Administrator access is required.</div></main>`;return;}
    const s=this.state, apps=(s?.apps||[]).filter(a=>(this.filter!=="installed"||a.installed)&&(`${a.name} ${a.category} ${a.summary}`.toLowerCase().includes(this.search.toLowerCase())));
    const resources=s?.resources||{};
    this.shadowRoot.innerHTML=this.css()+`<header><div><h1>Orange Pi Apps</h1><p>Native applications · managed here in Home Assistant</p></div><button id="refresh" title="Refresh status">Refresh</button></header><main>
      ${this.error?`<div class="error">${escapeHtml(this.error)}</div>`:""}
      ${s?.engine_error?`<div class="error">${escapeHtml(s.engine_error)}</div>`:""}
      <div class="summary"><div class="metric"><strong>${(s?.apps||[]).filter(a=>a.state==="running").length}</strong><span>apps running</span></div><div class="metric"><strong>${mib(resources.memory_available)}</strong><span>host memory available</span></div><div class="metric"><strong>${s?.reserve_mib??2048} MiB</strong><span>reserved from app budgets</span></div></div>
      ${s?.active_job?`<div class="notice" role="status">${escapeHtml(s.active_job.app)} · ${escapeHtml(s.active_job.stage)}</div>`:""}
      <div class="tools"><button id="all" class="${this.filter==='all'?'active':''}">Catalog</button><button id="installed" class="${this.filter==='installed'?'active':''}">Installed</button><input id="search" type="search" placeholder="Find an application" aria-label="Find an application" value="${escapeHtml(this.search)}"><button id="metrics">Resource details</button></div>
      <div class="grid">${apps.map(a=>this.card(a)).join("")}</div>
      ${!apps.length?`<div class="empty">${s?"No matching applications.":"Connecting to the local manager…"}</div>`:""}
      <p class="note">Reviewed native-container adapters, not Home Assistant Supervisor or the official App store. Your existing Home Assistant, kiosk, proxy and radio services stay independently managed. Apps remain stopped until you approve a start.</p>
    </main><dialog id="dialog"></dialog>`;
    this.shadowRoot.querySelector('#refresh').onclick=()=>this.refresh();
    for(const tab of ['all','installed'])this.shadowRoot.querySelector('#'+tab).onclick=()=>{this.filter=tab;this.render();};
    this.shadowRoot.querySelector('#search').oninput=e=>{this.search=e.target.value;const pos=e.target.selectionStart;this.render();const input=this.shadowRoot.querySelector('#search');input.focus();try{input.setSelectionRange(pos,pos);}catch{};};
    this.shadowRoot.querySelector('#metrics').onclick=()=>this.showMetrics();
    this.shadowRoot.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>this.action(b.dataset.app,b.dataset.action));
  }
  card(a){
    const blocked=this.busy||!!this.state?.active_job||!!this.state?.engine_error||['externally_managed','conflict','recovery_required'].includes(a.state);
    const button=(action,title,primary=false)=>`<button data-app="${a.id}" data-action="${action}" ${blocked?'disabled':''} class="${primary?'primary':''}">${title}</button>`;
    let buttons=a.installed?(a.state==='running'?(a.ingress?button('open','Open',true):'')+button('stop','Stop')+button('restart','Restart'):button('start','Start',true))+button('update','Settings / update')+button('logs','Logs')+button('remove','Remove') : button('install',a.state==='externally_managed'?'Managed by existing stack':'Install',true);
    if(a.id==='mosquitto'&&a.installed)buttons+=button('credentials','Connection');
    return `<article class="card" data-id="${a.id}"><div class="body"><div class="top"><ha-icon icon="${escapeHtml(a.icon)}"></ha-icon><h2>${escapeHtml(a.name)}</h2><span class="badge ${a.state==='running'?'running':''}">${escapeHtml(a.state.replaceAll('_',' '))}</span></div><p class="desc">${escapeHtml(a.summary)}</p><div class="details"><span>${escapeHtml(a.category)} · ${escapeHtml(a.options.version)}</span><span>${a.options.memory_mib} MiB ceiling</span></div></div><div class="actions">${buttons}</div></article>`;
  }
  modal(title,body){
    let d=this.shadowRoot.querySelector('dialog'); if(!d){d=document.createElement('dialog');this.shadowRoot.append(d);}
    d.innerHTML=`<h2>${escapeHtml(title)}</h2>${body}`;this.dialogOpen=true;d.onclose=()=>{if(!d.open&&!this.shadowRoot.querySelector("dialog[open]")){this.dialogOpen=false;d.innerHTML="";if(!this.selected)this.render();}};d.showModal();
    d.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>d.close());return d;
  }
  async action(slug,action){
    if(action==='open')return this.open(slug);
    if(action==='logs'){try{const r=await this.api('logs',{app:slug});this.modal('Private application logs',`<p>Logs can contain private data. Do not paste them into public issues.</p><pre>${escapeHtml(r.logs)}</pre><div class="buttons"><button data-close>Close</button></div>`);}catch(e){this.fail(e);}return;}
    if(action==='credentials'){const d=this.modal('Show private MQTT credentials?',`<p>These credentials will be visible on this screen. They are not logged.</p><div class="buttons"><button data-close>Cancel</button><button id="reveal" class="primary">Reveal</button></div>`);d.querySelector('#reveal').onclick=async()=>{try{const c=await this.api('credentials',{confirm:true});d.innerHTML=`<h2>MQTT connection</h2><p>HA host: <code>127.0.0.1:21883</code>. This manager’s apps: <code>opiha-apps-mosquitto:1883</code>.</p><pre>${escapeHtml(JSON.stringify(c,null,2))}</pre><button data-close>Close</button>`;d.querySelector('button').onclick=()=>{d.innerHTML='';d.close();};}catch(e){d.close();this.fail(e);}};return;}
    const a=this.state.apps.find(a=>a.id===slug);
    if(action==='install'||action==='update'){
      const o=a.options;const d=this.modal(`${action==='install'?'Install':'Update'} ${a.name}`,`<p>${escapeHtml(a.notes)}</p><form><div class="row"><label>Release tag<input name="version" value="${escapeHtml(o.version)}" required pattern="[0-9][A-Za-z0-9_.-]*"></label><label>Memory ceiling (MiB)<input name="memory_mib" type="number" min="${a.memory_mib}" max="32768" value="${o.memory_mib}" required></label></div><div class="row"><label>Loopback port<input name="port" type="number" min="20000" max="29999" value="${o.port}" required></label><label>CPU weight<input name="cpu_shares" type="number" min="64" max="1024" value="${o.cpu_shares}" required><small>A relative weight, not a hard CPU quota.</small></label></div><label><input name="autostart" type="checkbox" ${o.autostart?'checked':''}> Start on host boot after explicit first activation</label>${a.radio?`<label>Existing USB device path<input name="device" value="${escapeHtml(o.device)}" placeholder="/dev/serial/by-id/..."></label><label><input name="radio_reviewed" type="checkbox" ${o.radio_reviewed?'checked':''}> I preserved the original store/keys and stopped the old radio server.</label>`:''}<div class="buttons"><button type="button" data-close>Cancel</button><button class="primary">Review plan</button></div></form>`);
      d.querySelector('form').onsubmit=e=>{e.preventDefault();const f=e.currentTarget;const opts={...o,version:f.elements.version.value,memory_mib:Number(f.elements.memory_mib.value),port:Number(f.elements.port.value),cpu_shares:Number(f.elements.cpu_shares.value),autostart:f.elements.autostart.checked};if(a.radio){opts.device=f.elements.device.value;opts.radio_reviewed=f.elements.radio_reviewed.checked;}d.close();this.review(slug,action,opts);};
    }else this.review(slug,action);
  }
  async review(slug,action,options){
    try{const plan=await this.api('plan',{app:slug,action,...(options?{options}:{})});const d=this.modal('Review operation',`<p><strong>${escapeHtml(action)} ${escapeHtml(slug)}</strong></p><pre>${escapeHtml(JSON.stringify(plan,null,2))}</pre><p>Only this application is affected. Review network access, resource budgets and state before approving.</p><div class="buttons"><button data-close>Cancel</button><button class="primary" id="approve">Approve ${escapeHtml(action)}</button></div>`);d.querySelector('#approve').onclick=async()=>{d.close();try{const job=await this.api('apply',{id:plan.id,confirm:true});this.busy=true;this.follow(job.id);}catch(e){this.fail(e);}};}catch(e){this.fail(e);}
  }
  async follow(id){try{const j=await this.api('job',{id});if(this.state)this.state.active_job=j;this.render();if(['queued','running'].includes(j.status)&&this.isConnected){setTimeout(()=>this.follow(id),1500);return;}this.busy=false;await this.refresh();if(j.status!=='succeeded')this.fail(new Error(j.stage));}catch(e){this.busy=false;this.fail(e);}}
  async showMetrics(){try{const r=await this.api('metrics');this.modal('Measured host and application resources',`<p>On-demand sample. Memory ceilings are budgets, not reserved allocations or measured consumption. This is not an Orange Pi benchmark.</p><pre>${escapeHtml(JSON.stringify(r,null,2))}</pre><div class="buttons"><button data-close>Close</button></div>`);}catch(e){this.fail(e);}}
  fail(e){this.error=e.message||String(e);if(!this.selected)this.render();}
  async open(slug){
    try{const session=await this._hass.callApi('POST','opiha_apps/session',{app:slug});if(session.url!==`/api/opiha_apps/ingress/${slug}/`)throw new Error('Unexpected application route');
      this.selected=slug;this.shadowRoot.innerHTML=this.css()+`<header class="frame-head"><div><button id="back">← Apps</button> <strong>${escapeHtml(slug)}</strong><br><small>Protected by your active Home Assistant administrator session</small></div><button id="reload">Reload app</button></header><iframe class="app-frame" title="${escapeHtml(slug)}" referrerpolicy="no-referrer"></iframe>`;
      const frame=this.shadowRoot.querySelector('iframe');frame.src=session.url;
      this.shadowRoot.querySelector('#back').onclick=()=>{clearInterval(this.renewTimer);this.selected=null;this.render();this.refresh();};
      this.shadowRoot.querySelector('#reload').onclick=()=>this.open(slug);
      clearInterval(this.renewTimer);this.renewTimer=setInterval(async()=>{if(document.hidden)return;try{await this._hass.callApi('POST','opiha_apps/session',{app:slug});}catch(e){clearInterval(this.renewTimer);this.selected=null;this.fail(e);}},120000);
    }catch(e){this.fail(e);}
  }
}
if(!customElements.get('opiha-apps-panel'))customElements.define('opiha-apps-panel',OpihaAppsPanel);
