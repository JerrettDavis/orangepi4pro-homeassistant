import re
from opiha_apps import catalog


def test_every_reviewed_release_is_pinned_to_an_index_digest():
    for slug, app in catalog.CATALOG.items():
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", app["digest"]), slug
        reference = catalog.image(slug, {})
        assert reference == f"{app['repository']}:{app['version']}@{app['digest']}"


def test_non_catalog_tag_is_not_given_the_reviewed_digest():
    reference = catalog.image("nodered", {"version": "5.0.8"})
    assert reference == "nodered/node-red:5.0.8" and "@" not in reference


def test_radio_and_camera_apps_are_inactive_by_default():
    for slug in ("zwave", "go2rtc"):
        defaults = catalog.options(slug)
        assert defaults["autostart"] is False and defaults["device"] == "" and defaults["radio_reviewed"] is False
