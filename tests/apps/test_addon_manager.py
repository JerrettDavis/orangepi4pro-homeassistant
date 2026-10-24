from __future__ import annotations
import json
import pytest
from opiha_apps import addon_runtime, catalog
from opiha_apps.common import AppError
from opiha_apps.manager import Manager
from conftest import execute, execute_addon, wait

MOSQ = """name: Mosquitto broker
version: '6.5.2'
slug: mosquitto
description: An MQTT broker
arch: [aarch64, amd64]
image: homeassistant/{arch}-addon-mosquitto
apparmor: false
ports: {1883/tcp: 1883, 1884/tcp: null}
map: ['share:rw', ssl]
hassio_api: true
options: {require_certificate: false}
schema: {require_certificate: bool, name: 'str?'}
"""
EDITOR = """name: File editor
version: '5.8.0'
slug: configurator
description: Browser file editor
arch: [aarch64]
image: homeassistant/{arch}-addon-configurator
apparmor: false
ingress: true
ingress_port: 8099
map: [{type: homeassistant_config, read_only: false, path: /homeassistant}]
"""
BUILD = """name: Built thing
version: '1.0'
slug: built
description: Has a Dockerfile only
arch: [aarch64]
apparmor: false
"""


def make_repo(manager, files):
    def git(argv, cwd, timeout):
        if argv[0] == "clone":
            from pathlib import Path
            dest = Path(argv[-1])
            for rel, text in files.items():
                f = dest / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
        return 0, ""
    manager.repos.git = git
    return manager.repos.add("https://github.com/o/r")["id"]


@pytest.fixture
def repo(manager, tmp_path):
    manager.ha_config = str(tmp_path / "ha")
    return make_repo(manager, {"mosquitto/config.yaml": MOSQ, "configurator/config.yaml": EDITOR,
                               "built/config.yaml": BUILD, "built/Dockerfile": "ARG BUILD_FROM\nFROM $BUILD_FROM\n",
                               "built/build.yaml": "build_from:\n  aarch64: ghcr.io/home-assistant/aarch64-base:3.19\n"})


@pytest.fixture(autouse=True)
def clean_registry():
    catalog.clear_dynamic()
    yield
    catalog.clear_dynamic()


def slug(repo, name):
    return addon_runtime.slug_for(repo, name)


def test_plan_requires_the_privileges_the_manifest_asks_for(manager, repo):
    with pytest.raises(AppError, match="Approve these privileges"):
        manager.plan_addon(repo, "mosquitto")
    plan = manager.plan_addon(repo, "mosquitto", {"grants": ["ha_api"]})
    assert plan["action"] == "install" and plan["report"]["status"] == "reduced" and plan["privileges"][0]["id"] == "ha_api"
    assert not manager.engine.calls  # planning never pulls
    assert not catalog.is_addon(plan["app"])  # and does not register an uninstalled add-on


def test_install_creates_stopped_container_with_translated_spec(manager, repo):
    job = execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"], "config": {"require_certificate": True}})
    assert job["status"] == "succeeded", job["stage"]
    s = slug(repo, "mosquitto")
    assert catalog.is_addon(s)
    create = next(c for c in manager.engine.calls if c[0] == "create")[2]
    assert create["user"] == "0:0" and "NET_BIND_SERVICE" in create["cap_add"] and not create["privileged_mode"]
    assert (str(manager.app_dir(s) / "data"), "/data", False) in create["mounts"]
    assert any(dst == "/share" and not ro for _, dst, ro in create["mounts"])
    assert any(dst == "/ssl" and ro for _, dst, ro in create["mounts"])
    assert create["ports"] == [(21883, 1883)] and create["bind"] == "127.0.0.1"
    assert json.loads((manager.app_dir(s) / "data/options.json").read_text()) == {"require_certificate": True}
    env = (manager.app_dir(s) / "private.env").read_text()
    assert "SUPERVISOR_TOKEN=" in env and addon_runtime.token(manager, s)
    pull = next(c for c in manager.engine.calls if c[0] == "pull")
    assert pull[1] == "homeassistant/aarch64-addon-mosquitto:6.5.2"
    assert not manager.engine.owned(s)["State"]["Running"]


def test_installed_addon_survives_manager_restart_and_lists_in_overview(manager, repo):
    execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    s = slug(repo, "mosquitto")
    again = Manager(manager.config, engine=manager.engine, sampler=manager.sampler, check_port=False)
    try:
        assert catalog.is_addon(s)
        row = next(a for a in again.overview()["apps"] if a["id"] == s)
        assert row["kind"] == "addon" and row["state"] == "created" and row["manifest"]["slug"] == "mosquitto"
    finally:
        again.close()


def test_lifecycle_and_configure(manager, repo):
    execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    s = slug(repo, "mosquitto")
    assert execute(manager, s, "start")["status"] == "succeeded" and manager.engine.owned(s)["State"]["Running"]
    opts = {**manager.record(s)["options"], "config": {"require_certificate": True, "name": "x"}}
    assert execute(manager, s, "configure", opts)["status"] == "succeeded"
    assert json.loads((manager.app_dir(s) / "data/options.json").read_text())["name"] == "x"
    assert ("restart", s) in manager.engine.calls
    bad = {**opts, "config": {"require_certificate": "yes"}}
    with pytest.raises(AppError):
        manager.plan(s, "configure", bad)
    with pytest.raises(AppError):
        manager.plan(s, "install", None)  # add-ons only install from a repository listing
    assert execute(manager, s, "stop")["status"] == "succeeded"
    assert execute(manager, s, "remove")["status"] == "succeeded"


def test_write_access_to_ha_config_and_ingress_need_grants(manager, repo):
    with pytest.raises(AppError, match="homeassistant_config"):
        manager.plan_addon(repo, "configurator")
    job = execute_addon(manager, repo, "configurator", {"grants": ["write_homeassistant_config"]})
    assert job["status"] == "succeeded", job["stage"]
    s = slug(repo, "configurator")
    create = next(c for c in manager.engine.calls if c[0] == "create")[2]
    assert (manager.ha_config, "/homeassistant", False) in create["mounts"]
    assert create["loopback_ports"] == [] and create["network"] == "opiha-addons"
    assert create["aliases"] == ["a0d7b954-configurator"] or create["aliases"][0].endswith("-configurator")
    assert ("supervisor", "172.30.32.2") in create["extra_hosts"]
    assert catalog.entry(s)["ingress"] is True
    assert execute(manager, s, "start")["status"] == "succeeded"
    route = manager.ingress(s)
    assert route["host"] == "172.30.33.5" and route["port"] == 8099 and route["strip_prefix"] and route["prefix"].endswith(s + "/")


def test_addon_without_image_is_built_from_its_dockerfile(manager, repo):
    job = execute_addon(manager, repo, "built")
    assert job["status"] == "succeeded", job["stage"]
    s = slug(repo, "built")
    build = next(c for c in manager.engine.calls if c[0] == "build")
    assert build[3]["BUILD_FROM"] == "ghcr.io/home-assistant/aarch64-base:3.19" and build[3]["BUILD_ARCH"] == "aarch64"
    assert manager.record(s)["image"] == "sha256:" + "c" * 64
    assert not (manager.app_dir(s) / "build").exists()
    manager.test_host["disk_free"] = 3 * 1024**3
    with pytest.raises(AppError, match="4 GiB"):
        manager.plan_addon(repo, "built", {"memory_mib": 600})


def test_repository_changing_after_review_is_refused(manager, repo):
    plan = manager.plan_addon(repo, "built")
    (manager.repos.addon_dir(repo, "built") / "Dockerfile").write_text("FROM evil\n")
    job = wait(manager, manager.submit(plan["id"], True))
    assert job["status"] == "failed" and "changed after planning" in job["stage"]
    assert not catalog.is_addon(slug(repo, "built")) and not any(c[0] == "build" for c in manager.engine.calls)


def test_failed_first_install_leaves_no_registered_addon(manager, repo):
    manager.engine.fail_create = 1
    job = execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    assert job["status"] == "failed"
    s = slug(repo, "mosquitto")
    assert not catalog.is_addon(s)
    assert not (manager.root / "apps" / s / "addon.json").exists()
    assert manager.engine.owned(s) is None


def test_update_to_new_manifest_and_rollback_restores_old_manifest(manager, repo):
    execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    s = slug(repo, "mosquitto")
    folder = manager.repos.addon_dir(repo, "mosquitto")
    (folder / "config.yaml").write_text(MOSQ.replace("6.5.2", "6.6.0"))
    manager.engine.fail_create = 1
    failed = execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    assert failed["status"] == "failed"
    assert catalog.entry(s)["version"] == "6.5.2" and manager.record(s)["options"]["version"] == "6.5.2"
    assert manager.engine.owned(s) is not None
    ok = execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    assert ok["status"] == "succeeded" and catalog.entry(s)["version"] == "6.6.0"


def test_port_conflicts_and_lan_rules(manager, repo):
    with pytest.raises(AppError):
        manager.plan_addon(repo, "mosquitto", {"grants": ["ha_api"], "host_ports": {"1883/tcp": 1883}})
    with pytest.raises(AppError):
        manager.plan_addon(repo, "mosquitto", {"grants": ["ha_api"], "lan": True, "host_ports": {"1883/tcp": 8123}})
    p = manager.plan_addon(repo, "mosquitto", {"grants": ["ha_api"], "lan": True, "host_ports": {"1883/tcp": 1883}})
    assert any("LAN" in w for w in p["warnings"])


def test_reviewed_catalog_cannot_be_shadowed():
    with pytest.raises(AppError):
        catalog.register("nodered", {"x": 1})


def test_planning_and_overview_do_not_block_while_an_addon_installs(manager, repo):
    import threading
    gate, entered = threading.Event(), threading.Event()
    real_pull = manager.engine.pull

    def slow_pull(*args):
        entered.set()
        assert gate.wait(10)
        return real_pull(*args)
    manager.engine.pull = slow_pull
    plan = manager.plan_addon(repo, "mosquitto", {"grants": ["ha_api"]})
    job = manager.submit(plan["id"], True)
    assert entered.wait(5)
    done = []
    worker = threading.Thread(target=lambda: done.append((manager.overview(), manager.plan_addon(repo, "built"))))
    worker.start()
    worker.join(5)
    try:
        assert done, "planning/overview blocked behind a running add-on job"
        # Another thread must never see the job's private view of a not-yet-installed add-on.
        assert slug(repo, "mosquitto") not in [a["id"] for a in done[0][0]["apps"]]
    finally:
        gate.set()
    assert wait(manager, job)["status"] == "succeeded"
