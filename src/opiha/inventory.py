from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import sqlite3
from .common import ApplianceError, read_json


def inventory(config: Path) -> dict:
    """Identifiers and counts only. Never return config entry data, tokens or user names."""
    if not config.is_dir():
        raise ApplianceError("HA config directory does not exist")
    def storage(name: str, key: str) -> list:
        p = config / ".storage" / name
        if not p.exists():
            return []
        data = read_json(p).get("data", {})
        values = data.get(key, [])
        if not isinstance(values, list):
            raise ApplianceError(f"Unexpected HA storage shape: {name}")
        return values
    entries = storage("core.config_entries", "entries")
    entities = storage("core.entity_registry", "entities")
    devices = storage("core.device_registry", "devices")
    areas = storage("core.area_registry", "areas")
    version = config / ".HA_VERSION"
    custom = {}
    for p in sorted((config / "custom_components").glob("*/manifest.json")):
        try:
            item = read_json(p)
            custom[p.parent.name] = str(item.get("version", "unknown"))
        except ApplianceError:
            custom[p.parent.name] = "invalid-manifest"
    db = config / "home-assistant_v2.db"
    report = {"schema": 1, "ha_version": version.read_text().strip() if version.exists() else None,
              "integration_domains": dict(sorted(Counter(e.get("domain", "unknown") for e in entries).items())),
              "entry_ids": sorted(e["entry_id"] for e in entries if "entry_id" in e),
              "entity_ids": sorted(e["entity_id"] for e in entities if "entity_id" in e),
              "device_ids": sorted(e["id"] for e in devices if "id" in e),
              "area_ids": sorted(e["id"] for e in areas if "id" in e),
              "custom_components": custom,
              "database_bytes": db.stat().st_size if db.exists() else 0,
              "architecture_specific_files": sorted(str(p.relative_to(config)) for p in config.rglob("*.so")),
              "warnings": []}
    text = (config / "configuration.yaml").read_text(errors="replace") if (config / "configuration.yaml").exists() else ""
    if "db_url" in text:
        report["warnings"].append("External recorder database may be configured; inspect locally and back it up separately")
    if "ssl_certificate" in text:
        report["warnings"].append("Native HTTPS detected; configure ha_url/health check and copy /ssl separately")
    if "hassio" in report["integration_domains"]:
        report["warnings"].append("Supervisor integration/add-ons do not migrate to Container; inventory add-ons separately")
    report["warnings"].append("This report contains household identifiers. Keep it private even though credentials are omitted")
    return report


def compare(before: dict, after: dict) -> dict:
    differences = {}
    for key in ("entry_ids", "entity_ids", "device_ids", "area_ids"):
        left, right = set(before.get(key, [])), set(after.get(key, []))
        if left != right:
            differences[key] = {"missing": sorted(left - right), "added": sorted(right - left)}
    for key in ("integration_domains", "custom_components"):
        if before.get(key) != after.get(key):
            differences[key] = {"before": before.get(key), "after": after.get(key)}
    return {"matches": not differences, "differences": differences,
            "note": "Registry identity parity is not a live integration/functionality test"}


def sqlite_check(path: Path) -> str:
    if not path.exists():
        return "absent"
    # immutable is intentionally NOT used: a stopped DB may still have a valid WAL.
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        return "; ".join(row[0] for row in con.execute("PRAGMA quick_check"))
    finally:
        con.close()


def zwave_audit(store: Path) -> dict:
    settings = store / "settings.json"
    result = {"store_exists": store.is_dir(), "keys_present": [], "keys_invalid": [], "cache_files": 0}
    if settings.exists():
        data = read_json(settings)
        z = data.get("zwave", {})
        import re
        for group in ("securityKeys", "securityKeysLongRange"):
            for name, value in z.get(group, {}).items():
                dest = "keys_present" if isinstance(value, str) and re.fullmatch("[0-9a-fA-F]{32}", value) else "keys_invalid"
                result[dest].append(group + "." + name)
        if z.get("networkKey"):
            result["keys_present"].append("legacy networkKey (verify format locally)")
    result["cache_files"] = sum(1 for p in store.rglob("*") if p.is_file()) if store.exists() else 0
    result["note"] = "No key values printed. Preserve all S0/S2 and Long Range keys plus an NVM backup. No controller reset/re-inclusion is performed."
    return result
