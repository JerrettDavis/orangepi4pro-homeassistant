"""Desktops dashboard: fleet status at a glance, wake controls, wake-test history."""
from __future__ import annotations

from .common import chips, dashboard, grid, heading, md, section, stack, template_chip, tmpl, view

# name, MAC, LAN address, ping sensor (or None), wake button, wake verdict (label, color, icon), summary, detail
HOSTS = [
    dict(name="JDH-HYPERV-00", mac="00:e0:42:68:0a:88", ip="10.0.0.102", ping="binary_sensor.10_0_0_102",
         role="Hyper-V host · runs Home Assistant", verdict=("Wake unverified", "grey", "mdi:help-circle-outline"),
         detail="Wake button configured; manually powered on. Firmware/NIC wake settings and a physical wake "
                "remain unverified. Home Assistant runs on this host and cannot wake it while it is off."),
    dict(name="JDH-HYPERV-01", mac="54:04:a6:6f:b1:27", ip="10.0.0.103", ping="binary_sensor.10_0_0_103",
         role="Hyper-V host", verdict=("Packet sent, no wake yet", "orange", "mdi:alert-circle-outline"),
         detail="Correct magic packet verified on the LAN from Home Assistant. The machine is reported "
                "disconnected from the internet and its local LAN link is not confirmed. No successful physical "
                "wake has been verified."),
    dict(name="JDH-PRO-05", mac="74:56:3c:b2:bf:ad", ip="10.0.0.21", ping="binary_sensor.10_0_0_21",
         role="Workstation · off-system backup target", verdict=("Test pending", "blue", "mdi:flask-outline"),
         detail="Windows NIC magic-packet wake is configured. Firmware settings and a physical wake test remain."),
    dict(name="JDH-PRO-69", mac="08:71:90:a8:3e:dc", ip="10.0.0.44", ping="binary_sensor.10_0_0_44",
         role="Workstation (possibly formerly JDH-PRO-000)",
         verdict=("Wake failed", "red", "mdi:close-circle-outline"),
         detail="One Home Assistant wake command and an independent local-PC wake attempt each produced no "
                "management-port response within five minutes. The sender's exact magic packet was captured on "
                "the LAN. BIOS/NIC power settings are unverified."),
    dict(name="JDH-PRO-00", mac="00:e0:42:68:0a:8b", ip="10.0.0.12", ping=None,
         role="Hyper-V host (historical identity) · reserved address",
         verdict=("Wake failed", "red", "mdi:close-circle-outline"),
         detail="Verified Realtek 2.5GbE adapter. Windows magic-packet, shutdown and device wake are verified and "
                "PCI-E wake in BIOS is user-confirmed (ErP unverified). On September 18 one Home Assistant wake "
                "(08:05 CDT) and one local-PC wake (08:31 CDT) each produced no LAN return or TCP 135/445 "
                "response. The cause is unknown. ArkServer VM recovery is unverified; manual power-on and the ErP "
                "setting check are pending."),
    dict(name="JDH-PRO-01", mac="98:59:7a:b4:26:6b", ip="10.0.0.51", ping=None,
         role="Workstation (historical identity) · reserved address",
         verdict=("Wake failed", "red", "mdi:close-circle-outline"),
         detail="Reserved address and MAC matched domain DNS and gateway history; the gateway saw this MAC after "
                "power-on. One Home Assistant wake and one local-PC wake produced no management-port response "
                "within five minutes. BIOS/NIC power settings are unverified."),
]

MACS = [h["mac"] for h in HOSTS]


def _probe(mac: str) -> str:
    """Jinja prefix resolving the active-probe tracker for a MAC into `status` and `seen`."""
    return (
        "{% set p = namespace(e='') %}"
        "{% for e in integration_entities('nmap_tracker') %}"
        "{% if state_attr(e, 'mac') == '" + mac + "' and (not p.e or is_state(e, 'home')) %}{% set p.e = e %}{% endif %}"
        "{% endfor %}"
        "{% set seen = state_attr(p.e, 'last_time_reachable') if p.e else none %}"
        "{% set age = (as_timestamp(now()) - as_timestamp(seen, 0)) if seen else 0 %}"
        "{% if not p.e %}{% set status = 'undiscovered' %}"
        "{% elif states(p.e) in ['unknown', 'unavailable'] %}{% set status = 'unavailable' %}"
        "{% elif is_state(p.e, 'home') %}{% set status = 'stale' if seen and age > 120 else 'online' %}"
        "{% else %}{% set status = 'offline' %}{% endif %}"
    )


STATUS_TEXT = ("{{ {'online': 'Online · ARP reply', 'offline': 'No recent reply', 'stale': 'Probe data stale', "
               "'unavailable': 'Monitoring unavailable', 'undiscovered': 'Not discovered'}[status] }}")
STATUS_COLOR = ("{{ {'online': 'green', 'offline': 'red', 'stale': 'orange', 'unavailable': 'grey', "
                "'undiscovered': 'grey'}[status] }}")


def _host_card(h: dict) -> dict:
    probe = _probe(h["mac"])
    label, color, icon = h["verdict"]
    chip_row = [
        template_chip(label, icon, color),
        template_chip(probe + "{% if seen %}Last reply {{ relative_time(as_datetime(seen)) }} ago"
                      "{% else %}No reply recorded{% endif %}", "mdi:clock-outline", "grey"),
    ]
    if h["ping"]:
        chip_row.append(template_chip(
            "{% if is_state('" + h["ping"] + "','on') %}Ping reply{% elif is_state('" + h["ping"]
            + "','off') %}No ping{% else %}Ping unknown{% endif %}", "mdi:lan-pending", "grey"))
    wake = {
        "type": "custom:mushroom-entity-card",
        "entity": "button.wake_on_lan_" + h["mac"].replace(":", "_"),
        "name": "Send wake packet", "icon": "mdi:power", "icon_color": "blue", "fill_container": True,
        "layout": "horizontal",
        "tap_action": {"action": "perform-action", "perform_action": "button.press",
                       "target": {"entity_id": "button.wake_on_lan_" + h["mac"].replace(":", "_")}},
    }
    return stack([
        tmpl(h["name"], probe + h["ip"] + " · " + STATUS_TEXT, "mdi:desktop-tower-monitor", probe + STATUS_COLOR),
        chips(chip_row),
        wake,
    ])


def _fleet() -> dict:
    loop = "".join(_probe(m) + "{% set c.on = c.on + (1 if status == 'online' else 0) %}" for m in MACS)
    online = "{% set c = namespace(on=0) %}" + loop
    header = section([
        heading("Desktops", "mdi:desktop-tower-monitor"),
        grid([
            tmpl("Active LAN probe", online + "{{ c.on }} of " + str(len(HOSTS)) + " desktops answering ARP",
                 "mdi:lan-connect",
                 online + "{{ 'green' if c.on == " + str(len(HOSTS)) + " else 'orange' if c.on else 'red' }}"),
            tmpl("Wake-on-LAN", "Sends a magic packet only; never shuts down or restarts a running PC",
                 "mdi:power-sleep", "blue", multiline=True),
        ], 2),
    ], column_span=3)
    header["cards"].append(md(
        "<sub>Probed every 30 s by ARP, independent of ping. A reply proves network reachability, not OS power "
        "state; offline is declared after about 60–90 s. Home Assistant runs on HYPERV-00 and cannot wake it "
        "while it is off. Wake history is on the next tab.</sub>"))
    hosts = section([heading("Fleet", "mdi:server-network"), *[_host_card(h) for h in HOSTS[:3]]])
    hosts2 = section([heading("Workstations", "mdi:desktop-classic"), *[_host_card(h) for h in HOSTS[3:]]])
    return view("Fleet", "overview", "mdi:desktop-tower-monitor", [header, hosts, hosts2], max_columns=3)


def _wake_log() -> dict:
    cards = [heading("Wake verification log", "mdi:clipboard-text-clock-outline"),
             md("Results of controlled wake tests (September 18, 2026). A responding NIC proves reachability, "
                "not that the OS is awake.")]
    secs = [section(cards, column_span=3)]
    for h in HOSTS:
        label, color, icon = h["verdict"]
        secs.append(section([
            tmpl(h["name"], f"{h['role']} · {h['ip']}", "mdi:desktop-tower", color,
                 badge_icon=icon, badge_color=color, multiline=True),
            md(f"**{label}.** {h['detail']}\n\n<sub>MAC `{h['mac']}`</sub>"),
        ]))
    secs.append(section([
        heading("Other desktops to identify", "mdi:help-network-outline"),
        md("JDH-PRO-000 may be an earlier name for JDH-PRO-69 (unconfirmed). Directory/DNS or Tailscale records "
           "also mention PRO-02, PRO-03, PRO-06 and DESKTOP-V8UEH1S; their current wired MACs and hardware identity "
           "need verification. PRO-06 has an old address overlapping PRO-05. PRO-00 and PRO-01 have separate "
           "historical-identity wake buttons based on corroborated wired NIC records."),
    ], column_span=3))
    return view("Wake log", "wake-log", "mdi:clipboard-text-clock-outline", secs, max_columns=3)


def build() -> dict:
    return dashboard("Desktops", [_fleet(), _wake_log()])
