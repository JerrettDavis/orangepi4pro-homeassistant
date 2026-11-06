"""Lights dashboard: one tile per physical fixture, grouped by room.

Govee LED strips expose a cloud entity, a duplicate MQTT entity and up to 30
per-segment entities. SmartThings/TP-Link/Tuya also expose duplicate entities
for the same switch or bulb. Only the canonical entity for each fixture is
shown here; the Device map view documents what is intentionally left out.
"""
from __future__ import annotations

from .common import chips, dashboard, grid, heading, light_card, light_chip, md, section, stack, tmpl, view

LIVING_BULBS = ["light.ne_living_room_light", "light.nw_living_room_light",
                "light.se_living_room_light", "light.sw_living_room_light"]
LIVING_BULB_NAMES = ["NE", "NW", "SE", "SW"]

ROOM_FIXTURES: dict[str, list[str]] = {
    "Living Room": ["light.living_room_lights", "light.fireplace_light", "light.entertainment_center_dimmer",
                    "light.tv_backlight", "light.tv_floor_lights"],
    "Kitchen & Dining": ["light.kitchen_lights", "light.dining_room_light"],
    "Office": ["light.desk_lights", "light.office_hexa"],
    "Bedrooms": ["light.bedroom_ceiling_fan", "light.jd_bed_light", "light.sam_bed_light", "light.maya_lamp"],
    "Outside & Garage": ["light.back_string_lights", "light.driveway_cam_floodlight", "light.garage_door_light",
                         "light.baby_cam_floodlight", "switch.yard_lights", "switch.pole_lights",
                         "switch.inflatable_tree"],
}
ROOM_ICONS = {"Living Room": "mdi:sofa", "Kitchen & Dining": "mdi:silverware-fork-knife", "Office": "mdi:desk",
              "Bedrooms": "mdi:bed", "Outside & Garage": "mdi:home-lightbulb-outline"}

ACCESSORIES = {
    "3D printers": ["light.kitchen_p2s_chamber_light", "light.x2d_20p5aj661102691_chamber_light",
                    "light.v0_1_neopixel_bed", "light.v0_1_neopixel_caselight", "light.v0_1_neopixel_hotend_rgb"],
    "Air purifier nightlights": ["light.living_room_air_filter", "light.office_air_purifier"],
    "Network & status LEDs": ["light.jdh_ap_00_led", "light.jdh_ap_01_led", "light.jdh_ap_02_led",
                              "light.rfid_esp32_screen_status_led"],
}

FIXTURES = [e for room in ROOM_FIXTURES.values() for e in room]
ALL_PRIMARY = FIXTURES + [e for group in ACCESSORIES.values() for e in group]

# (fixture, room, controlled by, entity shown, entities intentionally left out)
DEVICE_MAP = [
    ("Living room ceiling bulbs ×4", "Living Room", "HS220 wall dimmer → 4 Govee bulbs",
     "light.living_room_lights", "light.living_room_lights_st (SmartThings copy of the dimmer)"),
    ("Fireplace bulb", "Living Room", "HS200 wall switch → Govee bulb", "light.fireplace_light",
     "switch.fireplace_light_switch, switch.fireplace_light_st"),
    ("Entertainment center", "Living Room", "Cync dimmer", "light.entertainment_center_dimmer", "—"),
    ("TV backlight", "Living Room", "Govee strip", "light.tv_backlight", "light.tv_backlight_2 + 15 segments"),
    ("TV floor lights", "Living Room", "Govee strip", "light.tv_floor_lights",
     "light.tv_floor_lights_2 + 15 segments"),
    ("Dining room light", "Kitchen & Dining", "HS200 wall switch", "light.dining_room_light",
     "switch.dining_room_light_switch, switch.dining_room_light_st"),
    ("Kitchen lights", "Kitchen & Dining", "Cync", "light.kitchen_lights", "—"),
    ("Desk lights", "Office", "Govee strip", "light.desk_lights", "light.desk_lights_2 + 15 segments"),
    ("Office hexa panels", "Office", "Govee panels", "light.office_hexa", "light.office_hexa_2 + 21 segments"),
    ("JD bed light", "Bedrooms", "Tuya bulb", "light.jd_bed_light", "light.jd_bed_light_2 (SmartThings copy)"),
    ("Back string lights", "Outside & Garage", "Govee string", "light.back_string_lights",
     "light.back_string_lights_2 + 30 segments"),
]


def _count(entities: list[str], states: str) -> str:
    return "(" + repr(entities) + " | select('is_state', " + states + ") | list | count)"


def _wall_chain(switch: str, name: str, model: str, bulbs: list[str], bulb_names: list[str], note: str) -> dict:
    """Wall control above the smart bulbs it powers, so the dependency is visible."""
    secondary = (
        model + " · {% if is_state('" + switch + "','off') %}Off at the wall — bulbs have no power"
        "{% elif is_state('" + switch + "','unavailable') %}Wall control unavailable"
        "{% else %}{{ " + repr(bulbs) + " | select('is_state','on') | list | count }} of "
        + str(len(bulbs)) + " bulbs on{% endif %}"
    )
    return stack([
        tmpl(name, secondary, "mdi:light-switch",
             "{{ 'amber' if is_state('" + switch + "','on') else 'grey' }}",
             tap={"action": "toggle"}, entity=switch, badge_icon="mdi:link-variant", badge_color="blue"),
        chips([light_chip(e, n) for e, n in zip(bulbs, bulb_names)]),
        md(f"<sub>{note}</sub>"),
    ])


def _room(name: str, cards: list[dict]) -> dict:
    return section([heading(name, ROOM_ICONS[name]), *cards])


def _simple(entity: str, name: str, icon: str) -> dict:
    return {"type": "custom:mushroom-entity-card", "entity": entity, "name": name, "icon": icon,
            "fill_container": True}


def _overview() -> dict:
    attention = (
        "{% set f = " + repr(ALL_PRIMARY) + " %}"
        "{% set off = f | select('is_state', ['unavailable','unknown']) | list %}"
        "{% if off %}**{{ off | count }} fixtures are offline:** "
        "{% for e in off %}{{ state_attr(e,'friendly_name') }}{{ ', ' if not loop.last }}{% endfor %}. "
        "Offline Govee entities usually mean the Govee-to-MQTT bridge, or the wall switch feeding the bulb, is off."
        "{% else %}All fixtures are reporting.{% endif %}"
    )
    header = section([
        heading("Lights", "mdi:lightbulb-group"),
        grid([
            tmpl("On", "{{ " + _count(FIXTURES, "'on'") + " }} of " + str(len(FIXTURES)),
                 "mdi:lightbulb-on", "{{ 'amber' if " + _count(FIXTURES, "'on'") + " > 0 else 'grey' }}"),
            tmpl("Offline", "{{ " + _count(ALL_PRIMARY, "['unavailable','unknown']") + " }} of "
                 + str(len(ALL_PRIMARY)), "mdi:lightbulb-alert-outline",
                 "{{ 'red' if " + _count(ALL_PRIMARY, "['unavailable','unknown']") + " > 0 else 'green' }}"),
            tmpl("Hidden", "{{ states.light | selectattr('entity_id','search','_segment_') | list | count }}"
                 " segments", "mdi:filter-variant", "blue"),
        ], 3),
        md(attention),
    ], column_span=3)

    living = _room("Living Room", [
        _wall_chain("light.living_room_lights", "Wall dimmer", "HS220", LIVING_BULBS, LIVING_BULB_NAMES,
                    "Powers the four Govee ceiling bulbs. Leave it on and control the bulbs as a group."),
        light_card("light.living_room_light_bulbs", "Ceiling bulbs · all four", color=True, temp=True),
        _wall_chain("light.fireplace_light", "Fireplace wall switch", "HS200", ["light.fireplace_bulb"], ["Bulb"],
                    "On/off switch that feeds the Govee fireplace bulb."),
        light_card("light.fireplace_bulb", "Fireplace bulb", color=True, temp=True),
        light_card("light.entertainment_center_dimmer", "Entertainment center"),
        light_card("light.tv_backlight", "TV backlight", color=True),
        light_card("light.tv_floor_lights", "TV floor lights", color=True),
    ])
    kitchen = _room("Kitchen & Dining", [
        light_card("light.kitchen_lights", "Kitchen"),
        light_card("light.dining_room_light", "Dining room", brightness=False),
    ])
    office = _room("Office", [
        light_card("light.desk_lights", "Desk lights", color=True),
        light_card("light.office_hexa", "Office hexa", color=True),
    ])
    bedrooms = _room("Bedrooms", [
        light_card("light.bedroom_ceiling_fan", "Bedroom ceiling fan light"),
        {"type": "custom:mushroom-fan-card", "entity": "fan.bedroom_ceiling_fan", "name": "Bedroom ceiling fan",
         "show_percentage_control": True, "collapsible_controls": True, "fill_container": True},
        light_card("light.jd_bed_light", "JD bed light"),
        light_card("light.sam_bed_light", "Sam bed light"),
        light_card("light.maya_lamp", "Maya's lamp", color=True),
    ])
    outside = _room("Outside & Garage", [
        light_card("light.back_string_lights", "Back string lights", color=True),
        light_card("light.driveway_cam_floodlight", "Driveway floodlight", brightness=False),
        light_card("light.baby_cam_floodlight", "Baby cam floodlight", brightness=False),
        light_card("light.garage_door_light", "Garage door light", brightness=False),
        _simple("switch.yard_lights", "Yard lights", "mdi:string-lights"),
        _simple("switch.pole_lights", "Pole lights", "mdi:led-strip-variant"),
        _simple("switch.inflatable_tree", "Inflatable tree", "mdi:pine-tree"),
    ])
    return view("Rooms", "rooms", "mdi:lightbulb-group", [header, living, kitchen, office, bedrooms, outside],
                max_columns=3)


def _accessories() -> dict:
    sections = [section([heading("Accessory & device lights", "mdi:led-strip-variant")], column_span=3)]
    for group, members in ACCESSORIES.items():
        sections.append(section([heading(group), *[light_card(e, brightness=False) for e in members]]))
    return view("Accessories", "accessories", "mdi:printer-3d", sections, max_columns=3)


def _device_map() -> dict:
    rows = []
    for fixture, room, control, entity, hidden in DEVICE_MAP:
        status = ("{{ '🟢 on' if is_state('" + entity + "','on') else '⚪ off' if is_state('" + entity
                  + "','off') else '🔴 offline' }}")
        rows.append(f"| {fixture} | {room} | {control} | `{entity}` | {status} | {hidden} |")
    table = (
        "| Fixture | Room | Controlled by | Entity shown | Now | Left out of dashboard |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows)
    )
    return view("Device map", "device-map", "mdi:sitemap", [
        section([
            heading("How lights are organised", "mdi:sitemap"),
            md(
                "**One tile per physical fixture.** Govee strips publish a cloud entity, a duplicate MQTT entity "
                "and one entity per LED segment. TP-Link, Tuya and SmartThings can all expose the same switch or "
                "bulb. Only the entity in *Entity shown* is used here, so nothing is controlled twice.\n\n"
                "**Wall switches that feed bulbs.** The HS200/HS220 wall controls power Govee bulbs. Turning the "
                "wall control off cuts power, and the bulbs then show as offline. Use the wall control for "
                "on/off and the bulb group for colour and brightness."
            ),
        ], column_span=3),
        section([md(table)], column_span=3),
    ], max_columns=3)


def build() -> dict:
    return dashboard("Lights", [_overview(), _accessories(), _device_map()])
