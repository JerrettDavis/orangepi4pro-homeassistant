from __future__ import annotations
import pytest
from opiha_apps import addon_repos
from opiha_apps.common import AppError

GOOD = "name: Demo\nslug: demo\nversion: '1.0'\ndescription: d\narch: [aarch64]\nimage: demo/{arch}-demo\n"


def fake_git(layout):
    calls = []

    def run(argv, cwd, timeout):
        calls.append((argv, cwd))
        if argv[0] == "clone":
            dest = __import__("pathlib").Path(argv[-1])
            for rel, text in layout.items():
                p = dest / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            (dest / ".git").mkdir()
        return 0, ""
    run.calls = calls
    return run


@pytest.mark.parametrize("url", [
    "http://github.com/a/b", "git@github.com:a/b", "https://user:pw@github.com/a/b", "https://localhost/a/b",
    "https://10.0.0.5/a/b", "https://github.com/a", "https://github.com/a/b?x=1", "https://github.com:8443/a/b",
    "file:///etc", "https://github.com/a/../b", "https://github.com/a/b c", "ssh://github.com/a/b", ""])
def test_hostile_urls_are_refused(url):
    with pytest.raises(AppError):
        addon_repos.normalise_url(url)


def test_url_is_canonicalised():
    assert addon_repos.normalise_url("https://github.com/Owner/Repo.git/") == "https://github.com/Owner/Repo"


def test_add_lists_and_removes_a_repository(tmp_path):
    git = fake_git({"repo.yaml": "name: My Repo\nmaintainer: Me\n", "demo/config.yaml": GOOD,
                    "broken/config.yaml": "slug: ../x\nname: x\nversion: '1'\n", "notes/readme.md": "x"})
    repos = addon_repos.Repositories(tmp_path, git=git)
    meta = repos.add("https://github.com/o/r")
    assert meta["name"] == "My Repo" and meta["id"] == addon_repos.repo_id("https://github.com/o/r")
    argv = git.calls[0][0]
    assert argv[:2] == ["clone", "--depth"] and "--no-recurse-submodules" in argv
    rows = {r["folder"]: r for r in repos.addons(meta["id"])}
    assert rows["demo"]["manifest"]["slug"] == "demo" and rows["demo"]["report"]["status"] in {"works", "reduced"}
    assert "error" in rows["broken"] and "notes" not in rows
    assert repos.addon_dir(meta["id"], "demo").name == "demo"
    with pytest.raises(AppError):
        repos.add("https://github.com/o/r")
    repos.remove(meta["id"])
    assert repos.list() == []


def test_repository_without_addons_or_failed_clone_leaves_nothing(tmp_path):
    repos = addon_repos.Repositories(tmp_path, git=fake_git({"README.md": "x"}))
    with pytest.raises(AppError):
        repos.add("https://github.com/o/empty")
    assert repos.list() == [] and not [p for p in repos.root.iterdir()]
    failing = addon_repos.Repositories(tmp_path, git=lambda *a: (128, "fatal"))
    with pytest.raises(AppError):
        failing.add("https://github.com/o/gone")
    assert not [p for p in failing.root.iterdir()]


def test_folder_and_id_traversal_refused(tmp_path):
    repos = addon_repos.Repositories(tmp_path, git=fake_git({"demo/config.yaml": GOOD}))
    meta = repos.add("https://github.com/o/r")
    for folder in ("..", "../x", ".git", "a/b", ""):
        with pytest.raises(AppError):
            repos.addon_dir(meta["id"], folder)
    for rid in ("../etc", "ZZZZZZZZ", "abc"):
        with pytest.raises(AppError):
            repos.remove(rid)
