"""Vehicle leases dashboard: visual lease progress, month pace and projected excess-mile fees."""
from __future__ import annotations

from .common import (chips, dashboard, entities, grid, heading, md, section, stack, template_chip, tmpl,
                     view)

VEHICLES = {
    "ioniq": {"name": "Ioniq 5 N", "icon": "mdi:car-electric", "odometer": "sensor.2025_ioniq_5_n_odometer"},
    "charger": {"name": "Dodge Charger", "icon": "mdi:car-sports", "odometer": "sensor.dodge_charger_odometer"},
}

# button-card JS: allowance bar with time-elapsed tick, projected end marker and a stat grid.
HERO_JS = r"""[[[
const v = '__V__';
const num = id => { const s = hass.states[id]; const n = s ? parseFloat(s.state) : NaN; return isNaN(n) ? 0 : n; };
const fmt = n => Math.round(n).toLocaleString();
const money = n => '$' + Math.round(n).toLocaleString();
const used = num(`sensor.lease_${v}_used_miles`), total = num(`sensor.lease_${v}_total_allowance`) || 1;
const proj = num(`sensor.lease_${v}_projected_miles`), fee = num(`sensor.lease_${v}_projected_cost`);
const remaining = num(`sensor.lease_${v}_remaining_miles`), safe = num(`sensor.lease_${v}_safe_monthly_miles`);
const weighted = num(`sensor.lease_${v}_weighted_monthly_miles`);
const st = hass.states[`input_datetime.lease_${v}_start`], en = hass.states[`input_datetime.lease_${v}_end`];
let timePct = 0;
if (st && en) { const a = new Date(st.state + 'T00:00:00'), b = new Date(en.state + 'T23:59:59');
  timePct = Math.min(100, Math.max(0, (Date.now() - a) / (b - a) * 100)); }
const scale = Math.max(total, proj, used) * 1.04;
const p = n => Math.min(100, n / scale * 100).toFixed(1);
const over = proj > total, ahead = used / total * 100 > timePct + 3;
const color = over ? '#e53935' : (ahead ? '#fb8c00' : '#43a047');
const label = over ? 'Projected over' : (ahead ? 'Ahead of pace' : 'On track');
const stat = (k, val, sub) => `<div style="flex:1;min-width:92px"><div style="font-size:11px;opacity:.65;text-transform:uppercase;letter-spacing:.04em">${k}</div><div style="font-size:20px;font-weight:600">${val}</div><div style="font-size:11px;opacity:.6">${sub || '&nbsp;'}</div></div>`;
return `
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
  <div style="font-size:12px;opacity:.7">Lease miles used vs. allowance</div>
  <div style="background:${color};color:#fff;border-radius:12px;padding:2px 10px;font-size:12px;font-weight:600">${label}</div>
</div>
<div style="position:relative;height:18px;background:var(--divider-color,#8883);border-radius:9px;overflow:visible">
  <div style="position:absolute;left:0;top:0;height:100%;width:${p(proj)}%;background:${color};opacity:.28;border-radius:9px"></div>
  <div style="position:absolute;left:0;top:0;height:100%;width:${p(used)}%;background:${color};border-radius:9px"></div>
  <div title="Time elapsed" style="position:absolute;left:${p(total * timePct / 100)}%;top:-4px;height:26px;width:3px;background:var(--primary-text-color);border-radius:2px"></div>
  <div title="Allowance" style="position:absolute;left:${p(total)}%;top:-4px;height:26px;width:2px;background:var(--primary-text-color);opacity:.5"></div>
</div>
<div style="position:relative;height:16px;font-size:11px;opacity:.7;margin-top:6px">
  <span style="position:absolute;left:${p(total * timePct / 100)}%;transform:translateX(-50%)">today ${timePct.toFixed(0)}%</span>
  <span style="position:absolute;right:0">${fmt(total)} mi allowance</span>
</div>
<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:14px">
  ${stat('Driven', fmt(used) + ' mi', (used / total * 100).toFixed(0) + '% of allowance')}
  ${stat('Remaining', fmt(remaining) + ' mi', 'safe ' + fmt(safe) + ' mi/mo')}
  ${stat('At lease end', fmt(proj) + ' mi', over ? '+' + fmt(proj - total) + ' over' : 'within allowance')}
  ${stat('Projected fee', money(fee), 'pace ' + fmt(weighted) + ' mi/mo')}
</div>`;
]]]"""


def _hero(v: str) -> dict:
    spec = VEHICLES[v]
    return {
        "type": "custom:button-card",
        "entity": f"sensor.lease_{v}_projected_miles",
        "show_name": False, "show_icon": False, "show_state": False,
        "tap_action": {"action": "none"}, "hold_action": {"action": "none"},
        "triggers_update": "all",
        "custom_fields": {"body": HERO_JS.replace("__V__", v)},
        "styles": {
            "card": [{"padding": "16px"}, {"border-radius": "var(--ha-card-border-radius,12px)"}],
            "grid": [{"grid-template-areas": '"body"'}, {"grid-template-columns": "1fr"}],
            "custom_fields": {"body": [{"width": "100%"}, {"text-align": "left"}]},
        },
    }


def _status(v: str) -> dict:
    spec = VEHICLES[v]
    return tmpl(
        spec["name"],
        "{% if not is_number(states('sensor.lease_" + v + "_monthly_miles')) %}Waiting for mileage data"
        "{% elif is_state('binary_sensor.lease_" + v + "_monthly_over_budget','on') %}Over this month's allowance"
        "{% elif states('sensor.lease_" + v + "_month_pace_delta')|float(0) > states('input_number.lease_warning_pace_miles')|float(100) %}"
        "Ahead of this month's pace{% else %}Within this month's pace{% endif %} · "
        "{{ states('sensor.lease_" + v + "_monthly_miles')|float(0)|round(0)|int }} of "
        "{{ states('sensor.lease_" + v + "_monthly_allowance')|float(0)|round(0)|int }} mi this month",
        spec["icon"],
        "{% if is_state('binary_sensor.lease_" + v + "_monthly_over_budget','on') %}red"
        "{% elif states('sensor.lease_" + v + "_month_pace_delta')|float(0) > states('input_number.lease_warning_pace_miles')|float(100) %}orange"
        "{% else %}green{% endif %}",
        entity=spec["odometer"], layout="horizontal",
    )


def _data_chips(v: str) -> dict:
    return chips([
        template_chip(
            "{% if is_state('input_boolean.lease_" + v + "_terms_confirmed','on') %}Terms confirmed"
            "{% else %}Dates provisional{% endif %}",
            "mdi:file-document-check-outline",
            "{{ 'green' if is_state('input_boolean.lease_" + v + "_terms_confirmed','on') else 'orange' }}"),
        template_chip(
            "{% set h = states('sensor.lease_" + v + "_data_age_hours')|float(999) %}"
            "{% if h > 72 %}Data {{ (h/24)|round(0)|int }}d old{% else %}Data {{ h|round(1) }} h old{% endif %}",
            "mdi:database-clock-outline",
            "{{ 'red' if states('sensor.lease_" + v + "_data_age_hours')|float(999) > 72 else 'grey' }}"),
    ])


def _vehicle_section(v: str) -> dict:
    spec = VEHICLES[v]
    return section([
        heading(spec["name"], spec["icon"]),
        _status(v),
        _hero(v),
        grid([
            {"type": "gauge", "entity": f"sensor.lease_{v}_monthly_percent", "name": "Month allowance used",
             "min": 0, "max": 150, "needle": True, "severity": {"green": 0, "yellow": 80, "red": 100}},
            {"type": "gauge", "entity": f"sensor.lease_{v}_projected_cost", "name": "Projected fee", "min": 0,
             "max": 500, "unit": "USD", "needle": True, "severity": {"green": 0, "yellow": 1, "red": 150}},
        ], 2),
        _data_chips(v),
    ])


def _overview() -> dict:
    guidance = tmpl(
        "{{ states('sensor.lease_driving_guidance') }}",
        "Combined projected excess-mile fees: ${{ states('sensor.lease_combined_projected_cost')|float(0)|round(0)|int }}"
        " · {{ states('sensor.lease_ioniq_remaining_days')|float(0)|round(0)|int }} days to lease end",
        "mdi:speedometer",
        "{{ 'red' if 'over' in states('sensor.lease_driving_guidance')|lower else 'green' }}",
        multiline=True,
    )
    top = section([
        heading("Vehicle leases", "mdi:car-multiple"),
        guidance,
        chips([
            template_chip("Ioniq 24,000 mi / 24 mo", "mdi:car-electric"),
            template_chip("Charger 30,000 mi / 24 mo", "mdi:car-sports"),
            template_chip("$0.10 per excess mile", "mdi:cash-multiple"),
            template_chip("Lease end Sep 30, 2027", "mdi:calendar-end"),
        ]),
        {"type": "custom:mushroom-chips-card", "chips": [
            {"type": "entity", "entity": "input_boolean.lease_notifications_enabled", "icon": "mdi:bell-outline",
             "content_info": "name", "name": "Push alerts"},
            {"type": "entity", "entity": "input_boolean.lease_charger_unavailable", "icon": "mdi:car-wrench",
             "content_info": "name", "name": "Charger in repair"},
        ]},
    ], column_span=2)
    trends = section([
        heading("Trends", "mdi:chart-line"),
        {"type": "statistics-graph", "title": "Odometer · last 90 days", "chart_type": "line", "period": "day",
         "days_to_show": 90, "stat_types": ["state"],
         "entities": [{"entity": VEHICLES[v]["odometer"], "name": VEHICLES[v]["name"]} for v in VEHICLES]},
        {"type": "statistics-graph", "title": "Daily miles · last 30 days", "chart_type": "bar", "period": "day",
         "days_to_show": 30, "stat_types": ["change"],
         "entities": [{"entity": VEHICLES[v]["odometer"], "name": VEHICLES[v]["name"]} for v in VEHICLES]},
        {"type": "history-graph", "title": "Pace gap · positive means ahead of budget", "hours_to_show": 168,
         "entities": [{"entity": f"sensor.lease_{v}_pace_delta", "name": VEHICLES[v]["name"]} for v in VEHICLES]},
    ], column_span=2)
    note = section([md(
        "<sub>Projections weight the last 7 days (default 60%) and 30 days (40%) and assume that pace continues "
        "to lease end. Excess-mile fees use each vehicle's total contract allowance; unused miles on one lease do "
        "not offset the other. Costs are estimates at the rate entered under Setup. The Charger's repair-period "
        "pace is not representative of normal use.</sub>")], column_span=2)
    return view("Overview", "overview", "mdi:car-multiple",
                [top, _vehicle_section("ioniq"), _vehicle_section("charger"), trends, note], max_columns=2)


ROWS = [
    ("monthly_miles", "Miles this calendar month"), ("monthly_allowance", "Monthly allowance"),
    ("month_pace_delta", "Ahead (+) / behind (−) month pace"), ("monthly_overage", "Over full monthly allowance"),
    ("monthly_overage_cost", "This month excess fee"), ("current_budget_overage", "Over cumulative budget today"),
    ("current_budget_cost", "Current budget overage fee"), ("pace_delta", "Ahead (+) / behind (−) lease pace"),
    ("remaining_miles", "Lease miles remaining"), ("safe_monthly_miles", "Monthly pace to stay within lease"),
]
PROJECTIONS = [
    ("weighted_monthly_miles", "Weighted pace, monthly"), ("weekly_daily_miles", "Last 7 days, mi/day"),
    ("recent_daily_miles", "Last 30 days, mi/day"), ("projected_miles", "Lease-end miles, weighted pace"),
    ("lifetime_projected_miles", "Lease-end miles, lifetime pace"), ("projected_overage", "Projected excess miles"),
    ("projected_cost", "Projected excess-mile fee"), ("already_incurred_cost", "Fee if no more miles driven"),
    ("data_age_hours", "Vehicle data age (hours)"),
]


def _details() -> dict:
    secs = [section([heading("Calculation detail", "mdi:table-large"),
                     md("Every figure behind the Overview, grouped by vehicle.")], column_span=2)]
    for v, spec in VEHICLES.items():
        secs.append(section([
            heading(spec["name"], spec["icon"]),
            entities("Month & lease", [{"entity": f"sensor.lease_{v}_{k}", "name": n} for k, n in ROWS]),
            entities("Projections", [{"entity": f"sensor.lease_{v}_{k}", "name": n} for k, n in PROJECTIONS]),
        ]))
    return view("Details", "details", "mdi:table-large", secs, max_columns=2)


def _downtime() -> dict:
    hero = grid([
        tmpl("Downtime", "{{ states('sensor.lease_downtime_days')|float(0)|round(0)|int }} days tracked",
             "mdi:car-wrench", "orange"),
        tmpl("Ioniq driven", "{{ states('sensor.lease_downtime_ioniq_miles')|float(0)|round(0)|int|string }} mi",
             "mdi:map-marker-distance", "blue"),
        tmpl("Above allowance pace", "{{ states('sensor.lease_downtime_excess_miles')|float(0)|round(0)|int }} excess mi",
             "mdi:gauge-full", "red"),
        tmpl("Potential cost", "${{ states('sensor.lease_downtime_cost_low')|float(0)|round(0)|int }}–"
             "${{ states('sensor.lease_downtime_cost_high')|float(0)|round(0)|int }} (range)", "mdi:cash", "red"),
    ], 2)
    top = section([
        heading("Charger downtime & Ioniq impact", "mdi:car-wrench"),
        md("{% if not is_state('input_boolean.lease_downtime_baseline_confirmed','on') %}"
           "**Start date estimated: March 8, 2026** (midpoint of an early-to-mid-March estimate); the range covers "
           "every start date March 1–15.{% else %}Incident baseline confirmed.{% endif %} Turn **Charger "
           "unavailable** off when it returns to freeze the record."),
        hero,
        md("<sub>Measured = Ioniq odometer change. Estimated = miles above the Ioniq's allowance pace (1,000/month). "
           "A planning baseline, not proof that each excess mile was caused by the wreck, and not a guarantee of "
           "insurance reimbursement. Marginal projected fee: "
           "${{ states('sensor.lease_downtime_marginal_projected_cost')|float(0)|round(0)|int }}.</sub>"),
    ], column_span=2)
    record = section([
        heading("Downtime record", "mdi:clipboard-text-clock"),
        entities("", [
            {"entity": "input_boolean.lease_charger_unavailable", "name": "Charger unavailable"},
            {"entity": "input_datetime.lease_downtime_start", "name": "Downtime start"},
            {"entity": "input_number.lease_downtime_ioniq_start_odometer", "name": "Ioniq odometer at start"},
            {"entity": "input_boolean.lease_downtime_baseline_confirmed", "name": "Baseline confirmed"},
            {"entity": "input_datetime.lease_downtime_end", "name": "Downtime end"},
            {"entity": "input_number.lease_downtime_ioniq_end_odometer", "name": "Ioniq final odometer"},
        ]),
    ])
    scenario = section([
        heading("After the Charger returns", "mdi:swap-horizontal"),
        {"type": "custom:mushroom-number-card", "entity": "input_number.lease_shift_monthly_miles",
         "name": "Monthly miles shifted to Charger", "display_mode": "slider", "icon": "mdi:swap-horizontal",
         "fill_container": True},
        grid([
            tmpl("Avoided fees", "{{ '-' if states('sensor.lease_shift_projected_savings')|float(0) < 0 }}$"
                 "{{ states('sensor.lease_shift_projected_savings')|float(0)|abs|round(0)|int }}",
                 "mdi:piggy-bank-outline",
                 "{{ 'green' if states('sensor.lease_shift_projected_savings')|float(0) > 0 else 'red' }}"),
            tmpl("Combined fees now", "${{ states('sensor.lease_combined_projected_cost')|float(0)|round(0)|int }}",
                 "mdi:cash-multiple", "orange"),
        ], 2),
        md("<sub>Assumes the shift starts now and lasts the Ioniq's remaining term, including any new Charger "
           "excess fee. Negative means the shift would cost more. Excludes energy, repair and operating costs.</sub>"),
    ])
    return view("Downtime & savings", "downtime", "mdi:car-wrench", [top, record, scenario], max_columns=2)


def _contract(v: str) -> dict:
    spec = VEHICLES[v]
    return section([
        heading(f"{spec['name']} contract", spec["icon"]),
        entities("", [
            {"entity": f"input_datetime.lease_{v}_start", "name": "Lease start"},
            {"entity": f"input_datetime.lease_{v}_end", "name": "Lease end (inclusive)"},
            {"entity": f"input_number.lease_{v}_start_odometer", "name": "Odometer at delivery"},
            {"entity": f"input_number.lease_{v}_annual_allowance", "name": "Annual allowance"},
            {"entity": f"input_number.lease_{v}_excess_rate", "name": "Excess-mile charge (USD/mi)"},
            {"entity": f"input_boolean.lease_{v}_terms_confirmed", "name": "Dates & delivery mileage confirmed"},
        ]),
    ])


def _setup() -> dict:
    intro = section([
        heading("Lease inputs", "mdi:tune"),
        md("Defaults: **Oct 1, 2025 – Sep 30, 2027** (24 months), starting odometers **0 mi** (enter the odometer "
           "at delivery, not today's). The excess charge is USD per mile (currently **$0.10**); **0 means unknown, "
           "not free**. Keep the 24-month term if you change dates. Confirmation switches only label the inputs."),
    ], column_span=2)
    notify = section([
        heading("Notifications", "mdi:bell-cog-outline"),
        entities("", [
            {"entity": "input_boolean.lease_notifications_enabled", "name": "Enable notifications"},
            {"entity": "input_number.lease_warning_pace_miles", "name": "Miles ahead of month pace before warning"},
            {"entity": "input_number.lease_recent_weight_percent", "name": "Weight on last 7 days (%)"},
            {"entity": "input_datetime.lease_last_warning", "name": "Last daily warning"},
        ]),
        md("<sub>Daily 6 PM warning if over budget, ahead of pace or projected over; threshold crossings can also warn "
           "8 AM–9 PM, at most once a day. Sunday 10 AM weekly summary to JD and Sam. Baselines refresh at 12:15 AM "
           "and on startup.</sub>"),
    ])
    return view("Setup", "setup", "mdi:tune", [intro, _contract("ioniq"), _contract("charger"), notify],
                max_columns=2)


def build() -> dict:
    return dashboard("Vehicle leases", [_overview(), _details(), _downtime(), _setup()])
