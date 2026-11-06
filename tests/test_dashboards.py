import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dashboards  # noqa: E402
from dashboard_defs.common import iter_cards, referenced_entities  # noqa: E402


def test_committed_storage_matches_generators():
    for name, config in dashboards.build_all().items():
        committed = json.loads((dashboards.OUT / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == json.loads(json.dumps(config)), f"run scripts/dashboards.py build ({name} is stale)"


def test_every_view_uses_sections_with_unique_paths():
    for name, config in dashboards.build_all().items():
        paths = [v["path"] for v in config["views"]]
        assert len(paths) == len(set(paths)), name
        assert all(v["type"] == "sections" and v["sections"] for v in config["views"]), name


def test_lights_dashboard_hides_segments_and_duplicates():
    refs = referenced_entities(dashboards.build_all(["lights"])["lights"])
    assert refs
    assert not [e for e in refs if "_segment_" in e]
    assert not [e for e in refs if e.endswith(("_2", "_st"))]


def test_physical_actions_require_confirmation():
    for name in ("home-operations",):
        config = dashboards.build_all([name])[name]
        for card in iter_cards(config):
            tap = card.get("tap_action", {})
            if tap.get("perform_action", "").split(".")[0] in {"lock", "cover"}:
                assert "confirmation" in tap, card


def test_no_secrets_in_built_dashboards():
    text = json.dumps(dashboards.build_all())
    assert "Bearer" not in text and "access_token" not in text
