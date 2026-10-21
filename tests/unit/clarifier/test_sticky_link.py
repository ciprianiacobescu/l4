"""The questions link in the sticky note opens on the forge it is on (github-parity L4-GHP-009; live run 38175559320 on
GitHub showed GitLab's `/-/blob/` there)."""

from pathlib import Path
from types import SimpleNamespace

from l4.clarifier.clarifier import sticky_location
from l4.config.schema import L4Config
from l4.forge.urls import blob_url


def test_blob_url_per_platform():
    assert blob_url("https://github.com/o/r", "l4/a", "x/q.md", "github") == "https://github.com/o/r/blob/l4/a/x/q.md"
    assert blob_url("https://gl.test/g/p", "l4/a", "x/q.md", "gitlab") == "https://gl.test/g/p/-/blob/l4/a/x/q.md"
    assert blob_url("https://github.com/o/r", "l4/a b", "x y.md", "github").endswith("/blob/l4/a%20b/x%20y.md")


def _ctx(tmp_path: Path, platform: str) -> SimpleNamespace:
    unit = tmp_path / "openspec" / "changes" / "u"
    unit.mkdir(parents=True)
    services = SimpleNamespace(
        ref=SimpleNamespace(path=unit), worktree=tmp_path, names=SimpleNamespace(branch="l4/openspec/u"),
        app=SimpleNamespace(environ={}, repo=tmp_path),
    )  # fmt: skip
    url = "https://github.com/o/r" if platform == "github" else "https://gl.test/g/p"
    cfg = L4Config.model_validate({"forge": {"type": platform}})
    return SimpleNamespace(services=services, shared={"project_url": url}, cfg=cfg)


def test_sticky_link_on_github_uses_blob(tmp_path):
    _, _, link = sticky_location(_ctx(tmp_path, "github"))
    assert link == "https://github.com/o/r/blob/l4/openspec/u/openspec/changes/u/questions.md"


def test_sticky_link_on_gitlab_keeps_the_separator(tmp_path):
    _, _, link = sticky_location(_ctx(tmp_path, "gitlab"))
    assert link == "https://gl.test/g/p/-/blob/l4/openspec/u/openspec/changes/u/questions.md"
