from __future__ import annotations
import pytest
from opiha_apps import addons
from opiha_apps.common import AppError

# Shaped like the real home-assistant/addons Mosquitto and File editor manifests.
MOSQUITTO = {
    "name": "Mosquitto broker", "version": "6.5.2", "slug": "mosquitto", "description": "An Open Source MQTT broker",
    "url": "https://github.com/home-assistant/addons/tree/master/mosquitto",
    "arch": ["armhf", "armv7", "aarch64", "amd64", "i386"], "startup": "services", "boot": "auto",
    "ports": {"1883/tcp": 1883, "8883/tcp": 8883, "1884/tcp": None},
    "map": ["share:rw", "ssl"], "host_network": False, "hassio_api": True, "auth_api": True,
    "services": ["mqtt:provide"], "discovery": ["mqtt"],
    "options": {"logins": [], "require_certificate": False, "certfile": "fullchain.pem"},
    "schema": {"logins": [{"username": "str", "password": "password?"}], "require_certificate": "bool",
               "certfile": "str", "customize": {"active": "bool", "folder": "str"}},
    "image": "homeassistant/{arch}-addon-mosquitto",
}
FILE_EDITOR = {
    "name": "File editor", "version": "5.8.0", "slug": "configurator", "description": "Simple browser-based file editor",
    "arch": ["aarch64", "amd64"], "ingress": True, "ingress_port": 8099, "panel_icon": "mdi:pencil",
    "map": [{"type": "homeassistant_config", "read_only": False, "path": "/homeassistant"}, "ssl:rw"],
    "homeassistant_api": True, "hassio_api": True, "hassio_role": "manager", "init": False,
    "options": {"dirsfirst": False}, "schema": {"dirsfirst": "bool", "theme": "list(dark|light)?"},
    "image": "homeassistant/{arch}-addon-configurator",
}


def test_parse_real_shaped_manifest_and_normalise_map_forms():
    m = addons.parse(FILE_EDITOR)
    assert m["slug"] == "configurator" and m["ingress"] and m["ingress_port"] == 8099
    assert {"type": "homeassistant_config", "read_only": False, "path": "/homeassistant"} in m["map"]
    assert {"type": "ssl", "read_only": False, "path": None} in m["map"]
    mq = addons.parse(MOSQUITTO)
    assert {"type": "ssl", "read_only": True, "path": None} in mq["map"]
    assert [p["container"] for p in mq["ports"]] == [1883, 8883, 1884]
    assert mq["ports"][2]["default_host"] is None


@pytest.mark.parametrize("patch", [
    {"slug": "../x"}, {"slug": ""}, {"version": "bad version"}, {"image": "Bad Image!"},
    {"map": ["root:rw"]}, {"map": ["ssl:wx"]}, {"ports": {"http": 80}}, {"devices": ["/etc/passwd"]},
    {"devices": ["/dev/../etc/shadow"]}, {"privileged": ["net admin"]}, {"hassio_role": "root"},
    {"environment": {"A B": "x"}}, {"services": ["docker"]}, {"host_network": "yes"}])
def test_parse_rejects_hostile_or_malformed_fields(patch):
    with pytest.raises(AppError):
        addons.parse({**FILE_EDITOR, **patch})


def test_renamed_map_types_are_normalised():
    m = addons.parse({**FILE_EDITOR, "map": ["app_config:rw", "all_app_configs:rw", {"type": "local_apps", "read_only": True}]})
    assert [e["type"] for e in m["map"]] == ["addon_config", "all_addon_configs", "addons"]


def test_report_works_reduced_and_unsupported():
    mq = addons.report(addons.parse(MOSQUITTO))
    assert mq["status"] == "reduced" and mq["notes"]  # auth_api reduces; AppArmor is only a note
    assert not any("AppArmor" in r for r in mq["reduced"])
    plain = addons.parse({**FILE_EDITOR, "apparmor": False, "hassio_role": "default", "homeassistant_api": False, "hassio_api": False})
    assert addons.report(plain)["status"] == "works"
    for blocker in ({"arch": ["armv7", "amd64"]}, {"host_dbus": True}, {"docker_api": True}, {"host_pid": True}):
        r = addons.report(addons.parse({**FILE_EDITOR, **blocker}))
        assert r["status"] == "unsupported" and r["blocked"]


def test_discovery_and_ha_api_are_reported_as_reduced_not_works():
    r = addons.report(addons.parse({**FILE_EDITOR, "apparmor": False, "hassio_role": "default", "discovery": ["mqtt"]}))
    assert r["status"] == "reduced" and any("discovery" in x.lower() for x in r["reduced"]) and any("WebSocket" in x for x in r["reduced"])
    with pytest.raises(AppError):
        addons.parse({**FILE_EDITOR, "discovery": "mqtt"})


def test_report_lists_privileges_for_approval():
    m = addons.parse({**FILE_EDITOR, "host_network": True, "privileged": ["NET_ADMIN", "SYS_ADMIN"],
                      "devices": ["/dev/ttyUSB0"], "full_access": True})
    ids = {p["id"]: p for p in addons.report(m)["privileges"]}
    assert {"host_network", "full_access", "capabilities", "devices", "write_homeassistant_config", "write_ssl", "ha_api"} <= set(ids)
    assert ids["capabilities"]["risk"] == "high" and ids["host_network"]["risk"] == "high"


def test_reading_the_ha_config_directory_needs_approval_too():
    m = addons.parse({**FILE_EDITOR, "map": ["homeassistant_config:ro", "config", "ssl"]})
    ids = {p["id"]: p for p in addons.report(m)["privileges"]}
    assert ids["read_homeassistant_config"]["risk"] == "high" and "read_config" in ids and "read_ssl" not in ids


def test_schema_validation_accepts_good_options_and_applies_optionals():
    schema = addons.parse(MOSQUITTO)["schema"]
    good = {"logins": [{"username": "u"}], "require_certificate": True, "certfile": "x.pem",
            "customize": {"active": False, "folder": "mosquitto"}}
    assert addons.validate_options(schema, good)["logins"] == [{"username": "u"}]


@pytest.mark.parametrize("schema,value", [
    ({"a": "int(1,10)"}, {"a": 11}), ({"a": "int(1,10)"}, {"a": True}), ({"a": "bool"}, {"a": "true"}),
    ({"a": "list(x|y)"}, {"a": "z"}), ({"a": "match(^[a-z]+$)"}, {"a": "ABC"}), ({"a": "port"}, {"a": 70000}),
    ({"a": "email"}, {"a": "nope"}), ({"a": "url"}, {"a": "ftp://x"}), ({"a": "str"}, {}),
    ({"a": "str"}, {"a": "x", "b": "y"}), ({"a": ["int"]}, {"a": ["x"]}), ({"a": "bogus"}, {"a": 1}),
    ({"a": "device"}, {"a": "/etc/passwd"}), ({"a": "float(0,1)"}, {"a": 2.5}), ({"a": "str(3,5)"}, {"a": "toolongvalue"})])
def test_schema_validation_rejects_bad_options(schema, value):
    with pytest.raises(AppError):
        addons.validate_options(schema, value)


def test_optional_marker_and_no_options_addon():
    assert addons.validate_options({"a": "str?"}, {}) == {}
    assert addons.validate_options(False, {}) == {}
    with pytest.raises(AppError):
        addons.validate_options(False, {"a": 1})


def test_read_document_bounds_and_symlinks(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("name: X\nslug: x\nversion: '1'\n")
    assert addons.read_document(f)["slug"] == "x"
    big = tmp_path / "big.yaml"
    big.write_text("a: " + "x" * (addons.MAX_MANIFEST + 1))
    with pytest.raises(AppError):
        addons.read_document(big)
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(AppError):
        addons.read_document(bad)
    link = tmp_path / "link.yaml"
    try:
        link.symlink_to(f)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(AppError):
        addons.read_document(link)
