"""`l4 upgrade` tells which open unit branches keep a workflow copy that pins another harness (fix-043 B): a push to
one of them runs that copy, whose pin guard (CFG-008) then does no work. Local remote-tracking refs only, no network."""

from collections.abc import Callable
from pathlib import Path

from l4.cli import main

from .conftest import HarnessRemote

WORKFLOW = ".github/workflows/l4.yml"
OLD_REF = "refs/remotes/origin/l4/openspec/old"
NEW_REF = "refs/remotes/origin/l4/openspec/current"
NOTE = "keep the old workflow copy"


def adopt(target: Path, remote: HarnessRemote) -> None:
    flags = ("--action", "--action-repo", "o/harness", "--harness-ref", "v0.3.0")
    assert main(["init", "--repo", str(target), "--ci", "github", *flags], environ=remote.environ) == 0


def upgrade(target: Path, remote: HarnessRemote, *flags: str) -> int:
    return main(["upgrade", "--repo", str(target), "--harness-ref", "v0.4.0", *flags], environ=remote.environ)


def track(target: Path, raw: Callable[..., str], ref: str, workflow: str) -> None:
    """A commit holding `workflow`, kept as the remote-tracking ref `ref` (it is made on a scratch branch)."""
    kept = (target / WORKFLOW).read_text()
    raw(target, "checkout", "-q", "-b", "scratch")
    (target / WORKFLOW).write_text(workflow)
    raw(target, "add", "-f", WORKFLOW)
    raw(target, "commit", "-q", "-m", "copy")
    raw(target, "update-ref", ref, "HEAD")
    raw(target, "checkout", "-q", "-")
    raw(target, "branch", "-q", "-D", "scratch")
    (target / WORKFLOW).parent.mkdir(parents=True, exist_ok=True)
    (target / WORKFLOW).write_text(kept)  # the work tree keeps the adopted file


def adopted_with_branches(target: Path, remote: HarnessRemote, raw: Callable[..., str]) -> None:
    adopt(target, remote)
    text = (target / WORKFLOW).read_text()
    assert remote.old in text
    track(target, raw, OLD_REF, text)
    track(target, raw, NEW_REF, text.replace(remote.old, remote.new))


def test_a_unit_branch_with_the_old_pin_is_named(target, harness_remote, raw, capsys):
    adopted_with_branches(target, harness_remote, raw)
    capsys.readouterr()
    assert upgrade(target, harness_remote) == 0
    out = capsys.readouterr().out
    assert NOTE in out and "l4/openspec/old" in out
    assert "l4/openspec/current" not in out
    assert "a push to one of them does no work" in out and "l4 retry" in out and "l4 questions" in out
    assert out.count(NOTE) == 1


def test_no_unit_branch_means_no_note(target, harness_remote, raw, capsys):
    adopt(target, harness_remote)
    capsys.readouterr()
    assert upgrade(target, harness_remote) == 0
    assert NOTE not in capsys.readouterr().out


def test_branches_that_already_pin_the_new_commit_are_not_named(target, harness_remote, raw, capsys):
    adopt(target, harness_remote)
    track(target, raw, NEW_REF, (target / WORKFLOW).read_text().replace(harness_remote.old, harness_remote.new))
    capsys.readouterr()
    assert upgrade(target, harness_remote) == 0
    assert NOTE not in capsys.readouterr().out


def test_an_upgrade_that_changes_no_pin_is_silent(target, harness_remote, raw, capsys):
    adopted_with_branches(target, harness_remote, raw)
    assert upgrade(target, harness_remote) == 0
    capsys.readouterr()
    assert upgrade(target, harness_remote) == 0  # up to date now: nothing moved, nothing to say
    assert NOTE not in capsys.readouterr().out


def test_a_dry_run_names_them_too(target, harness_remote, raw, capsys):
    adopted_with_branches(target, harness_remote, raw)
    capsys.readouterr()
    assert upgrade(target, harness_remote, "--dry-run") == 0
    assert "l4/openspec/old" in capsys.readouterr().out


def test_a_fetched_adoption_compares_harness_commit_of_the_branch_config(target, harness_remote, raw, capsys):
    flags = ("--harness-repo", harness_remote.URL, "--harness-ref", "v0.3.0")
    assert main(["init", "--repo", str(target), "--ci", "github", *flags], environ=harness_remote.environ) == 0
    config = target / ".l4/config.yaml"
    old_text = config.read_text()
    raw(target, "checkout", "-q", "-b", "scratch")
    raw(target, "add", "-f", ".l4/config.yaml")
    raw(target, "commit", "-q", "-m", "config")
    raw(target, "update-ref", OLD_REF, "HEAD")
    raw(target, "checkout", "-q", "-")
    raw(target, "branch", "-q", "-D", "scratch")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(old_text)
    capsys.readouterr()
    assert upgrade(target, harness_remote) == 0
    out = capsys.readouterr().out
    assert NOTE in out and "l4/openspec/old" in out
