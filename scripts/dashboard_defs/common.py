"""Small builders shared by the dashboard definitions.

Cards rely on the community plugins already loaded in the deployed Home
Assistant: Mushroom, button-card, mini-graph-card and auto-entities.
"""
from __future__ import annotations

NO_TAP = {"action": "none"}


def title(text: str, subtitle: str = "") -> dict:
    return {
        "type": "custom:mushroom-title-card",
        "title": text,
        "subtitle": subtitle,
        "alignment": "start",
    }


def heading(text: str, icon: str | None = None, badges: list[dict] | None = None, style: str = "title") -> dict:
    card = {"type": "heading", "heading": text, "heading_style": style}
    if icon:
        card["icon"] = icon
    if badges:
        card["badges"] = badges
    return card


def tmpl(primary: str, secondary: str = "", icon: str = "", color: str = "", *, tap: dict | None = None,
         entity: str | None = None, picture: str = "", badge_icon: str = "", badge_color: str = "",
         multiline: bool = False, layout: str = "horizontal", fill: bool = True) -> dict:
    card = {
        "type": "custom:mushroom-template-card",
        "primary": primary,
        "secondary": secondary,
        "icon": icon,
        "icon_color": color,
        "tap_action": tap or NO_TAP,
        "hold_action": NO_TAP,
        "layout": layout,
        "fill_container": fill,
    }
    if entity:
        card["entity"] = entity
    if picture:
        card["picture"] = picture
    if badge_icon:
        card["badge_icon"] = badge_icon
        card["badge_color"] = badge_color or "blue"
    if multiline:
        card["multiline_secondary"] = True
    return card


def chips(items: list[dict], alignment: str = "start") -> dict:
    return {"type": "custom:mushroom-chips-card", "alignment": alignment, "chips": items}


def template_chip(content: str, icon: str = "", color: str = "", tap: dict | None = None) -> dict:
    chip = {"type": "template", "content": content, "icon": icon, "icon_color": color,
            "tap_action": tap or NO_TAP}
    return chip


def light_chip(entity: str, name: str | None = None) -> dict:
    chip = {"type": "light", "entity": entity, "use_light_color": True, "content_info": "name"}
    if name:
        chip["name"] = name
    return chip


def light_card(entity: str, name: str | None = None, *, brightness: bool = True, color: bool = False,
               temp: bool = False, secondary: str = "state") -> dict:
    card = {
        "type": "custom:mushroom-light-card",
        "entity": entity,
        "use_light_color": True,
        "show_brightness_control": brightness,
        "show_color_control": color,
        "show_color_temp_control": temp,
        "collapsible_controls": True,
        "secondary_info": secondary,
        "fill_container": True,
        "layout": "horizontal",
    }
    if name:
        card["name"] = name
    return card


def entity_card(entity: str, name: str | None = None, icon: str | None = None, tap: dict | None = None,
                **extra) -> dict:
    card = {"type": "custom:mushroom-entity-card", "entity": entity, "fill_container": True}
    if name:
        card["name"] = name
    if icon:
        card["icon"] = icon
    if tap:
        card["tap_action"] = tap
    card.update(extra)
    return card


def confirm(service: str, entity: str, text: str) -> dict:
    return {
        "action": "perform-action",
        "perform_action": service,
        "target": {"entity_id": entity},
        "confirmation": {"text": text},
    }


def md(content: str, card_title: str = "") -> dict:
    card = {"type": "markdown", "content": content}
    if card_title:
        card["title"] = card_title
    return card


def grid(cards: list[dict], columns: int = 2) -> dict:
    return {"type": "grid", "columns": columns, "square": False, "cards": cards}


def stack(cards: list[dict]) -> dict:
    return {"type": "vertical-stack", "cards": cards}


def hstack(cards: list[dict]) -> dict:
    return {"type": "horizontal-stack", "cards": cards}


def entities(title_text: str, items: list, **extra) -> dict:
    card = {"type": "entities", "title": title_text, "show_header_toggle": False, "entities": items}
    card.update(extra)
    return card


def section(cards: list[dict], column_span: int = 1) -> dict:
    sec = {"type": "grid", "cards": cards}
    if column_span != 1:
        sec["column_span"] = column_span
    return sec


def view(title_text: str, path: str, icon: str, sections: list[dict], max_columns: int = 4) -> dict:
    return {
        "type": "sections",
        "title": title_text,
        "path": path,
        "icon": icon,
        "max_columns": max_columns,
        "sections": sections,
    }


def dashboard(title_text: str, views: list[dict]) -> dict:
    return {"title": title_text, "views": views}


def iter_cards(node):
    """Yield every card-like dict in a dashboard tree."""
    if isinstance(node, dict):
        if "type" in node and isinstance(node["type"], str):
            yield node
        for value in node.values():
            yield from iter_cards(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_cards(value)


ENTITY_KEYS = ("entity", "entity_id")


def referenced_entities(node) -> set[str]:
    """Static entity ids referenced by a dashboard (templates are not parsed)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ENTITY_KEYS and isinstance(value, str) and "." in value and " " not in value:
                found.add(value)
            elif key == "entities" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and "." in item:
                        found.add(item)
                    else:
                        found |= referenced_entities(item)
            else:
                found |= referenced_entities(value)
    elif isinstance(node, list):
        for value in node:
            found |= referenced_entities(value)
    return found
