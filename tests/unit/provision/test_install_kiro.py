"""The Kiro install from its versioned archive (L4-PRV-042, L4-PRV-043, L4-OCG-005, design D2) and the exact
verification after an install in CI (L4-PRV-043). Nothing here touches the network: a fake fetcher serves a tiny zip."""

import hashlib
import stat
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.provision import catalog, install
from l4.provision.catalog import kiro_archive_url
from l4.provision.install import install_planned
from l4.provision.runner import OfflineError

from ._install_helpers import FakeFetcher, InstallRunner, KiroRunner, installer, kiro_zip

URL = kiro_archive_url("2.32.0", "linux-x64")


class Fetch403(FakeFetcher):
    def download(self, url, dest):
        self.calls.append(url)
        raise OfflineError("prod.download.cli.kiro.dev", "HTTP 403")


@pytest.fixture
def world(paths, env, install_fake, monkeypatch):
    """A runner with uv, a kiro-cli profile in a role chain, and the digest table pointing at the test archive."""
    install_fake("uv")

    def make(archive: bytes | None = None, *, kiro: str | None = None, ci: bool = False, fetcher=None, **kw):
        archive = kiro_zip() if archive is None else archive
        monkeypatch.setitem(catalog.KIRO_SHA256["2.32.0"], "linux-x64", hashlib.sha256(archive).hexdigest())
        if kiro is not None:
            paths.local_bin.mkdir(parents=True, exist_ok=True)
            (paths.local_bin / "kiro-cli").write_text(f"#!/bin/sh\n# kiro-cli {kiro}\n")
            (paths.local_bin / "kiro-cli").chmod(0o755)
        runner = KiroRunner(paths, env, {"uv": "uv 0.12.22"})
        fetcher = fetcher or FakeFetcher({URL: archive})
        cfg = L4Config.model_validate(
            {"profiles": {"k": {"adapter": "kiro-cli"}}, "roles": {"implementer": ["k"], "judges": []}}
        )
        before = {p.name: p.read_bytes() for p in paths.local_bin.glob("*") if p.is_file()}
        done = install_planned(
            cfg, paths, env, "linux-x64", openspec_active=False, fetcher=fetcher, run=runner, replace_present=ci, **kw
        )
        return {a.tool: a for a in done}["kiro-cli"], fetcher, runner, before

    return make


def left_over(paths) -> list[str]:
    return sorted(p.name for p in paths.local_bin.glob(".*tmp*"))


def test_installs_the_three_members_with_mode_755(world, paths):  # SCN-PRV-113
    action, fetcher, runner, before = world()
    assert action.status == "applied" and action.message == "kiro-cli 2.32.0"
    assert fetcher.calls == [URL]
    assert sorted(p.name for p in paths.local_bin.iterdir()) == sorted(
        ["uv", "kiro-cli", "kiro-cli-chat", "kiro-cli-term"]
    )
    for name in ("kiro-cli", "kiro-cli-chat", "kiro-cli-term"):
        assert stat.S_IMODE((paths.local_bin / name).stat().st_mode) == 0o755
    assert {c[1:] for c in runner.calls if Path(c[0]).name == "kiro-cli"} == {("--version",)}  # nothing else ran
    assert not [p for p in (paths.l4_cache / "installers").glob("*")]  # the temporary directory is gone


def test_a_digest_mismatch_changes_nothing(world, paths, monkeypatch):  # SCN-PRV-114
    monkeypatch.setattr(catalog, "KIRO_VERSION", "2.32.0")
    archive = kiro_zip()
    action, fetcher, _, before = world(archive, kiro="2.27.1", ci=True)
    assert action.status == "applied"  # baseline: the matching digest installs
    other = kiro_zip(reported="2.99.9")
    action, _, _, _ = world(other, kiro="3.0.0", ci=True, fetcher=FakeFetcher({URL: archive}))
    assert action.status == "failed"
    assert hashlib.sha256(other).hexdigest() in action.message and hashlib.sha256(archive).hexdigest() in action.message
    assert "run manually" in action.message and "sha256sum -c" in action.message
    assert "3.0.0" in (paths.local_bin / "kiro-cli").read_text()  # untouched
    assert left_over(paths) == [] and not list((paths.l4_cache / "installers").glob("*"))


@pytest.mark.parametrize(
    "kwargs,named",
    [
        ({"links": ("kiro-cli-chat",)}, "kirocli/bin/kiro-cli-chat"),
        ({"skip": ("kiro-cli-term",)}, "kirocli/bin/kiro-cli-term"),
    ],
    ids=["linked", "missing"],
)
def test_a_linked_or_missing_member_fails(world, paths, kwargs, named):  # SCN-PRV-116
    action, _, _, _ = world(kiro_zip(**kwargs), kiro="2.27.1", ci=True)
    assert action.status == "failed" and named in action.message
    assert "2.27.1" in (paths.local_bin / "kiro-cli").read_text()
    assert not (paths.local_bin / "kiro-cli-chat").exists() and left_over(paths) == []


def test_a_missing_member_fails(world, paths):
    action, _, _, _ = world(kiro_zip(skip=("kiro-cli-chat",)))
    assert action.status == "failed" and "kirocli/bin/kiro-cli-chat" in action.message
    assert not (paths.local_bin / "kiro-cli").exists()


def test_an_oversized_member_fails(world, paths, monkeypatch):
    monkeypatch.setattr(install, "KIRO_MEMBER_MAX", 10)
    action, _, _, _ = world()
    assert action.status == "failed" and "kirocli/bin/" in action.message and "larger" in action.message
    assert not (paths.local_bin / "kiro-cli").exists() and left_over(paths) == []


def test_a_wrong_major_after_the_install_names_the_path(world, paths):  # L4-OCG-005
    action, _, _, _ = world(kiro_zip(reported="3.0.0"))
    assert action.status == "failed"
    assert action.message.startswith(
        f"kiro-cli at {paths.local_bin / 'kiro-cli'} reports 3.0.0 (Kiro CLI 3) after the install, "
        "need kiro-cli 2.x (pinned 2.32.0)"
    )


def test_ci_replaces_a_regular_kiro_file(world, paths):  # SCN-OCG-13
    action, fetcher, _, _ = world(kiro="3.0.0", ci=True)
    assert action.status == "applied" and action.message == "kiro-cli 2.32.0" and fetcher.calls == [URL]
    assert "kiro-cli 2.32.0" in (paths.local_bin / "kiro-cli").read_text()


def test_a_staging_error_removes_the_staged_files(world, paths):  # SCN-PRV-116
    paths.local_bin.mkdir(parents=True, exist_ok=True)
    old = {name: f"old {name}\n" for name in ("kiro-cli-term", "kiro-cli-chat")}
    for name, body in old.items():
        (paths.local_bin / name).write_text(body)
    action, _, _, _ = world(kiro_zip(corrupt="kiro-cli-chat"), kiro="2.27.1", ci=True)
    assert action.status == "failed" and "run manually" in action.message
    assert left_over(paths) == []
    assert {n: (paths.local_bin / n).read_text() for n in old} == old
    assert "2.27.1" in (paths.local_bin / "kiro-cli").read_text()


def test_a_403_is_failed_with_the_manual_command(world, paths):
    action, fetcher, _, _ = world(fetcher=Fetch403())
    assert action.status == "failed" and "HTTP 403" in action.message
    assert "sha256sum -c" in action.message and "kirocli-x86_64-linux.zip" in action.message
    assert fetcher.calls == [URL] and left_over(paths) == []


def test_ci_verifies_the_exact_version(paths, env, install_fake):  # SCN-PRV-119
    install_fake("uv")
    install_fake("claude")
    cfg = L4Config.model_validate({"profiles": {"c": {"adapter": "claude-code"}}, "roles": {"implementer": ["c"]}})
    fetcher = FakeFetcher({catalog.INSTALLER_URLS["claude-code"]: installer("claude")})

    def run(replace_present: bool, claude_says: str):
        runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "claude": claude_says})
        done = install_planned(
            cfg,
            paths,
            env,
            "linux-x64",
            openspec_active=False,
            fetcher=fetcher,
            run=runner,
            replace_present=replace_present,
        )
        return {a.tool: a for a in done}["claude"]

    failed = run(True, "2.1.300 (Claude Code)")
    assert failed.status == "failed" and "installed 2.1.300, but 2.1.288 (pinned) is needed" in failed.message
    (paths.local_bin / "claude").unlink()
    applied = run(False, "2.1.288 (Claude Code)")  # a missing Claude, installed at the pin: applied as today
    assert applied.status == "applied"
