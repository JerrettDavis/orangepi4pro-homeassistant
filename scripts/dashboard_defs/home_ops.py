"""Home Operations dashboard: status-first overview, alerts, maintenance and settings."""
from __future__ import annotations

from .common import chips, confirm, dashboard, entities, grid, heading, md, section, stack, template_chip, tmpl, view

ISSUES = [
    ("input_boolean.homeops_security_front_door_active", "Front door risk is active", "mdi:door-open"),
    ("input_boolean.homeops_security_garage_active", "Garage door risk is active", "mdi:garage-open"),
    ("input_boolean.homeops_health_front_door_unavailable", "Front door monitoring unavailable", "mdi:lock-alert"),
    ("input_boolean.homeops_health_garage_unavailable", "Garage monitoring unavailable", "mdi:garage-alert"),
    ("input_boolean.homeops_health_jd_location_stale", "JD's phone location is stale", "mdi:cellphone-marker"),
    ("input_boolean.homeops_health_sam_location_stale", "Sam's phone location is stale", "mdi:cellphone-marker"),
    ("input_boolean.homeops_health_backup_stale", "Automatic backup is stale", "mdi:backup-restore"),
    ("input_boolean.homeops_health_disk_pressure", "Home Assistant disk pressure", "mdi:harddisk-remove"),
]
ISSUE_IDS = [i[0] for i in ISSUES]
ACTIVE = "(" + repr(ISSUE_IDS) + " | select('is_state','on') | list | count)"

SNOOZED = ("{% set sn = states('input_datetime.homeops_snooze_until') %}"
           "{% set snoozed = sn not in ['unknown','unavailable','none',''] and as_timestamp(sn, 0) > as_timestamp(now()) %}")


def _status_hero() -> dict:
    return tmpl(
        "{% if " + ACTIVE + " == 0 %}All clear{% else %}{{ " + ACTIVE + " }} active issue"
        "{{ 's' if " + ACTIVE + " > 1 }}{% endif %}",
        SNOOZED + "{% if snoozed %}Alerts snoozed until {{ as_local(as_datetime(sn)).strftime('%-I:%M %p') }}"
        "{% elif " + ACTIVE + " == 0 %}No security or monitoring incidents · alerts active"
        "{% else %}See Alerts for details{% endif %}",
        "{{ 'mdi:shield-check' if " + ACTIVE + " == 0 else 'mdi:shield-alert' }}",
        "{{ 'green' if " + ACTIVE + " == 0 else 'red' }}",
        tap={"action": "navigate", "navigation_path": "/dashboard-home-operations/alerts"}, multiline=True,
    )


def _person(person: str, tracker: str, name: str) -> dict:
    return tmpl(
        name,
        "{{ states('" + person + "') | replace('_',' ') | title }} · "
        "{% set src = states['" + tracker + "'] %}{% set seen = src.last_reported | default(src.last_updated, true) %}"
        "{% set age = ((as_timestamp(now()) - as_timestamp(seen)) / 60) | round(0) %}"
        "{% set limit = states('input_number.homeops_phone_freshness_minutes') | float(120) %}"
        "{% if src.state in ['unknown','unavailable'] %}location unavailable"
        "{% elif age > limit %}stale · reported {{ relative_time(seen) }} ago"
        "{% else %}reported {{ relative_time(seen) }} ago{% endif %}",
        "mdi:account-circle",
        "{% set src = states['" + tracker + "'] %}{% set seen = src.last_reported | default(src.last_updated, true) %}"
        "{% set age = ((as_timestamp(now()) - as_timestamp(seen)) / 60) | round(0) %}"
        "{{ 'red' if src.state in ['unknown','unavailable'] else 'orange' if age > states('input_number.homeops_phone_freshness_minutes') | float(120) "
        "else 'green' if is_state('" + person + "','home') else 'blue' }}",
        picture="{{ state_attr('" + person + "','entity_picture') }}", entity=person,
    )


def _door_controls() -> list[dict]:
    lock, garage = "lock.front_door_deadbolt", "cover.garage_door"
    ok = lambda e: [{"condition": "state", "entity": e, "state_not": "unavailable"},
                    {"condition": "state", "entity": e, "state_not": "unknown"}]

    def action(entity: str, state: str, name: str, icon: str, service: str, text: str, color: str) -> dict:
        return {"type": "conditional",
                "conditions": [{"condition": "state", "entity": entity, "state": state}],
                "card": tmpl(name, "Tap to " + name.split()[0].lower() + " · asks to confirm", icon, color,
                             tap=confirm(service, entity, text))}

    return [
        tmpl("Front door",
             "{% set s = states('" + lock + "') %}{% if s in ['locked','unlocked'] %}{{ s | title }} · updated "
             "{{ relative_time(states." + lock + ".last_updated) }} ago{% elif s == 'jammed' %}Jammed — security "
             "cannot be confirmed{% elif s in ['unknown','unavailable'] %}Unavailable — security cannot be confirmed"
             "{% else %}{{ s | replace('_',' ') | title }} — wait for a final state{% endif %}",
             "{{ 'mdi:lock' if is_state('" + lock + "','locked') else 'mdi:lock-open-alert' }}",
             "{{ 'green' if is_state('" + lock + "','locked') else 'red' }}", entity=lock, multiline=True),
        action(lock, "unlocked", "Lock front door", "mdi:lock", "lock.lock", "Lock the front door now?", "green"),
        action(lock, "locked", "Unlock front door", "mdi:lock-open-variant", "lock.unlock",
               "Unlock the front door now?", "orange"),
        tmpl("Garage door",
             "{% set s = states('" + garage + "') %}{% if s in ['open','opening','closed','closing'] %}"
             "{{ s | title }} · updated {{ relative_time(states." + garage + ".last_updated) }} ago"
             "{% elif s in ['unknown','unavailable'] %}Unavailable — security cannot be confirmed"
             "{% else %}{{ s | replace('_',' ') | title }}{% endif %}",
             "{{ 'mdi:garage' if is_state('" + garage + "','closed') else 'mdi:garage-open' }}",
             "{{ 'green' if is_state('" + garage + "','closed') else 'orange' }}", entity=garage, multiline=True),
        action(garage, "open", "Close garage", "mdi:garage", "cover.close_cover", "Close the garage door now?",
               "green"),
        action(garage, "closed", "Open garage", "mdi:garage-open", "cover.open_cover", "Open the garage door now?",
               "orange"),
    ]


def _health_cards() -> list[dict]:
    return [
        tmpl("Backup",
             "{% set l = states('sensor.backup_last_successful_automatic_backup') %}"
             "{% if l in ['unknown','unavailable'] %}No successful backup timestamp{% else %}Last success "
             "{{ relative_time(as_datetime(l)) }} ago{% endif %}",
             "mdi:backup-restore",
             "{{ 'red' if is_state('input_boolean.homeops_health_backup_stale','on') else 'green' }}",
             tap={"action": "navigate", "navigation_path": "/dashboard-home-operations/maintenance"}),
        tmpl("Storage", "{{ states('sensor.system_monitor_disk_usage_config') }}% used · "
             "{{ states('sensor.system_monitor_disk_free_config') }} GiB free", "mdi:harddisk",
             "{{ 'red' if is_state('input_boolean.homeops_health_disk_pressure','on') else 'green' }}",
             tap={"action": "navigate", "navigation_path": "/dashboard-home-operations/maintenance"}),
        tmpl("Internet", "WAN {{ states('sensor.jdh_gateway_00_interface_wan_status') }} · "
             "{{ 'DNS reachable' if is_state('binary_sensor.1_1_1_1','on') else 'no reply from 1.1.1.1' }}",
             "mdi:wan",
             "{{ 'green' if is_state('sensor.jdh_gateway_00_interface_wan_status','up') and is_state('binary_sensor.1_1_1_1','on') else 'red' }}"),
    ]


def _alert_switches() -> dict:
    return chips([
        {"type": "entity", "entity": e, "icon": i, "content_info": "name", "name": n}
        for e, i, n in [
            ("input_boolean.homeops_presence_alerts_enabled", "mdi:account-switch", "Presence"),
            ("input_boolean.homeops_security_alerts_enabled", "mdi:shield-lock", "Security"),
            ("input_boolean.homeops_health_alerts_enabled", "mdi:heart-pulse", "Health"),
            ("input_boolean.homeops_digest_enabled", "mdi:email-newsletter", "Digest"),
        ]
    ] + [
        template_chip("Snooze 1 h", "mdi:bell-sleep-outline", "blue",
                      tap={"action": "perform-action", "perform_action": "script.turn_on",
                           "target": {"entity_id": "script.homeops_snooze_one_hour"}}),
        template_chip("Resume", "mdi:bell-ring-outline", "green",
                      tap={"action": "perform-action", "perform_action": "script.turn_on",
                           "target": {"entity_id": "script.homeops_resume_alerts"}}),
    ])


def _overview() -> dict:
    top = section([
        heading("Home Operations", "mdi:home-heart"),
        _status_hero(),
        _alert_switches(),
    ], column_span=3)
    people = section([
        heading("People", "mdi:account-multiple"),
        _person("person.jd", "device_tracker.jd_s23_ultra", "JD"),
        _person("person.sam", "device_tracker.sam_s_s23_ultra_2", "Sam"),
        md("<sub>Confidence uses the phone's last report time, not when someone changed zones. Unknown, "
           "unavailable or stale location is never treated as confirmed away.</sub>"),
    ])
    doors = section([
        heading("Doors & garage", "mdi:door"),
        *_door_controls(),
        md("<sub>Controls move physical devices; each asks for confirmation.</sub>"),
    ])
    health = section([heading("System health", "mdi:heart-pulse"), *_health_cards()])
    return view("Overview", "overview", "mdi:home-heart", [top, people, doors, health], max_columns=3)


def _alerts() -> dict:
    cards = []
    for entity, text, icon in ISSUES:
        cards.append(tmpl(text.replace(" is active", "").replace(" is stale", ""),
                          "{{ 'Active' if is_state('" + entity + "','on') else 'Clear' }}", icon,
                          "{{ 'red' if is_state('" + entity + "','on') else 'green' }}"))
    summary = section([
        heading("Alerts", "mdi:alert-circle-outline"),
        _status_hero(),
        md("{% set sn = states('input_datetime.homeops_snooze_until') %}"
           "Notifications this incident — front door: **{{ states('input_number.homeops_security_front_door_notification_count')|int(0) }}**"
           " · garage: **{{ states('input_number.homeops_security_garage_notification_count')|int(0) }}**."),
    ], column_span=3)
    status = section([heading("Incident & monitoring state", "mdi:list-status"), grid(cards, 2)], column_span=2)
    controls = section([
        heading("Controls", "mdi:tune-variant"),
        entities("Enable alerts", [
            "input_boolean.homeops_presence_alerts_enabled", "input_boolean.homeops_security_alerts_enabled",
            "input_boolean.homeops_health_alerts_enabled", "input_boolean.homeops_digest_enabled",
            "input_boolean.homeops_health_include_sam"]),
        entities("Timing", [
            "input_datetime.homeops_security_night_start", "input_datetime.homeops_security_night_end",
            "input_number.homeops_security_followup_minutes", "input_number.homeops_security_reminder_minutes",
            "input_number.homeops_availability_grace_minutes"]),
    ])
    return view("Alerts", "alerts", "mdi:alert-circle-outline", [summary, status, controls], max_columns=3)


def _calendar() -> dict:
    return view("Calendar", "calendar", "mdi:calendar-month-outline", [
        section([
            heading("Family calendar", "mdi:calendar-month-outline"),
            {"type": "calendar", "entities": ["calendar.family"], "initial_view": "listWeek"},
        ], column_span=2),
        section([
            heading("Source status", "mdi:calendar-sync-outline"),
            tmpl("Google", "Connected · Family calendar supplies the agenda", "mdi:google", "green", multiline=True),
            tmpl("Outlook", "Sign-in complete, but Microsoft rejected calendar access (HTTP 401); no entity yet",
                 "mdi:microsoft-outlook", "orange", multiline=True),
            md("<sub>Only the shared Family calendar is shown; personal, work, birthday, holiday, Todoist and "
               "automated calendars are excluded. No automatic reminders are enabled.</sub>"),
        ]),
    ], max_columns=3)


def _maintenance() -> dict:
    backup = section([
        heading("Backup", "mdi:backup-restore"),
        tmpl("Automatic backup",
             "{% set l = states('sensor.backup_last_successful_automatic_backup') %}"
             "{% if l in ['unknown','unavailable'] %}No successful-backup timestamp{% else %}"
             "{{ as_local(as_datetime(l)).strftime('%b %-d at %-I:%M %p') }} ({{ relative_time(as_datetime(l)) }} ago)"
             "{% endif %} · manager {{ states('sensor.backup_backup_manager_state') | replace('_',' ') }}",
             "mdi:cloud-check-outline",
             "{{ 'red' if is_state('input_boolean.homeops_health_backup_stale','on') else 'green' }}", multiline=True),
        entities("Schedule", [
            {"entity": "sensor.backup_last_attempted_automatic_backup", "name": "Last attempt"},
            {"entity": "sensor.backup_next_scheduled_automatic_backup", "name": "Next scheduled"}]),
        md("**Off-system archive (PRO-05)** — 141,037 snapshots and 154 Home Assistant backups, checksum-verified "
           "through Sep 18, 6:26 PM CDT. Daily pull at 6:00 AM while jd is logged on and PRO-05 is awake; failures "
           "raise a persistent notification.\n\n**Camera snapshots** — full verified history on PRO-05; most recent "
           "30 days (37,583 files, 2.47 GB) kept on Home Assistant."),
    ])
    storage = section([
        heading("Storage & connectivity", "mdi:harddisk"),
        {"type": "gauge", "entity": "sensor.system_monitor_disk_usage_config", "name": "/config used",
         "min": 0, "max": 100, "needle": True, "severity": {"green": 0, "yellow": 80, "red": 85}},
        tmpl("Free space", "{{ states('sensor.system_monitor_disk_free_config') }} GiB available on /config",
             "mdi:harddisk", "blue"),
        chips([
            template_chip("Gateway {{ 'up' if is_state('binary_sensor.10_0_0_1','on') else 'down' }}", "mdi:router-network",
                          "{{ 'green' if is_state('binary_sensor.10_0_0_1','on') else 'red' }}"),
            template_chip("Internet {{ 'up' if is_state('binary_sensor.1_1_1_1','on') else 'down' }}", "mdi:web",
                          "{{ 'green' if is_state('binary_sensor.1_1_1_1','on') else 'red' }}"),
        ]),
        entities("Disk health thresholds", ["input_number.homeops_disk_warning_percent",
                                            "input_number.homeops_disk_recovery_percent"]),
    ])
    devices = section([
        heading("Devices", "mdi:battery-heart-variant"),
        {"type": "custom:mushroom-entity-card", "entity": "sensor.front_door_deadbolt_battery_level",
         "name": "Front door lock", "fill_container": True},
        {"type": "custom:mushroom-entity-card", "entity": "sensor.jd_s23_ultra_battery_level", "name": "JD's phone",
         "fill_container": True},
        {"type": "custom:mushroom-entity-card", "entity": "sensor.samsung_s23_ultra_battery_level",
         "name": "Sam's phone", "fill_container": True},
        md("{% if states('lock.front_door_deadbolt') in ['unknown','unavailable'] %}**Door monitoring disconnected:** "
           "Home Assistant cannot reach the external Z-Wave JS server, so front-door security cannot be confirmed."
           "{% elif is_state('lock.front_door_deadbolt','jammed') %}**Lock fault:** the front door reports jammed."
           "{% else %}Door monitoring healthy.{% endif %}"),
    ])
    return view("Maintenance", "maintenance", "mdi:tools", [backup, storage, devices], max_columns=3)


def _settings() -> dict:
    return view("Settings", "settings", "mdi:tune-variant", [
        section([
            heading("Alerts", "mdi:bell-cog-outline"),
            entities("Alert switches", [
                "input_boolean.homeops_presence_alerts_enabled", "input_boolean.homeops_security_alerts_enabled",
                "input_boolean.homeops_health_alerts_enabled", "input_boolean.homeops_digest_enabled",
                "input_boolean.homeops_health_include_sam"]),
        ]),
        section([
            heading("Presence", "mdi:account-switch"),
            entities("Presence", [
                "input_datetime.homeops_presence_quiet_start", "input_datetime.homeops_presence_quiet_end",
                "input_number.homeops_presence_debounce_seconds", "input_number.homeops_phone_freshness_minutes"]),
        ]),
        section([
            heading("Security & health", "mdi:shield-lock"),
            entities("Security and health", [
                "input_datetime.homeops_security_night_start", "input_datetime.homeops_security_night_end",
                "input_datetime.homeops_snooze_until", "input_number.homeops_security_followup_minutes",
                "input_number.homeops_security_reminder_minutes", "input_number.homeops_availability_grace_minutes"]),
        ]),
    ], max_columns=3)


def build() -> dict:
    return dashboard("Home Operations", [_overview(), _alerts(), _calendar(), _maintenance(), _settings()])
