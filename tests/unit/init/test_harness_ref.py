"""`--harness-ref REF` for `l4 init` and `l4 upgrade` (adoption-kit L4-ACT-005, SCN-ACT-10): one `git ls-remote`, the
sha and the ref written as `@<sha> # <REF>`; the remote is a local bare repository (no network)."""

from pathlib import Path

import pytest
import yaml

from l4.ci.github import ActionPin, render_github_action_ci
from l4.cli import main
from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.init.action import resolve_ref

from .conftest import HarnessRemote

WORKFLOW = ".github/workflows/l4.yml"
SHA = "c" * 40


def init(target: Path, environ, *flags: str) -> int:
    return main(["init", "--repo", str(target), "--ci", "github", *flags], environ=environ)


def upgrade(target: Path, environ, *flags: str) -> int:
    return main(["upgrade", "--repo", str(target), *flags], environ=environ)


def adopt(target: Path, remote: HarnessRemote) -> None:
    flags = ("--action", "--action-repo", "o/harness", "--harness-ref", "v0.3.0")
    assert init(target, remote.environ, *flags) == 0


def uses_line(target: Path) -> str:
    return next(ln.strip() for ln in (target / WORKFLOW).read_text().splitlines() if "uses: o/harness" in ln)


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b)
    return [(x, y) for x, y in zip(a, b, strict=True) if x != y]


def test_a_lightweight_tag_resolves_to_its_commit(harness_remote: HarnessRemote):
    assert resolve_ref(harness_remote.URL, "v0.3.0", harness_remote.environ) == harness_remote.old


def test_an_annotated_tag_resolves_to_the_commit_not_the_tag_object(harness_remote: HarnessRemote):
    sha = resolve_ref(harness_remote.URL, "v0.4.0", harness_remote.environ)
    assert sha == harness_remote.new != harness_remote.tag_object


def test_a_branch_resolves_to_its_head(harness_remote: HarnessRemote):
    assert resolve_ref(harness_remote.URL, "dev", harness_remote.environ) == harness_remote.old


def test_a_tag_wins_over_a_branch_of_the_same_name(harness_remote: HarnessRemote, raw, tmp_path):
    raw(harness_remote.bare, "branch", "v0.4.0", harness_remote.old)
    assert resolve_ref(harness_remote.URL, "v0.4.0", harness_remote.environ) == harness_remote.new


@pytest.mark.parametrize("ref", ["v9.9.9", "v0", "--upload-pack=x", "a b", "", "x;y"])
def test_an_unresolved_or_malformed_ref_is_exit_2_naming_it(harness_remote: HarnessRemote, ref):
    with pytest.raises(L4Exit) as caught:
        resolve_ref(harness_remote.URL, ref, harness_remote.environ)
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert repr(ref) in str(caught.value) or ref in str(caught.value)


def test_an_unreachable_remote_is_exit_2(tmp_path, git_environ):
    with pytest.raises(L4Exit) as caught:
        resolve_ref(str(tmp_path / "nowhere.git"), "v1", git_environ)
    assert caught.value.code == ExitCode.USAGE_ERROR and "v1" in str(caught.value)


def test_init_writes_sha_and_ref(target: Path, harness_remote: HarnessRemote):
    """SCN-ACT-08 / SCN-ACT-10: `uses: …@<sha> # v0.3.0`."""
    flags = ("--action", "--action-repo", "o/harness", "--harness-ref", "v0.3.0")
    assert init(target, harness_remote.environ, *flags) == 0
    assert uses_line(target) == f"uses: o/harness/.github/actions/l4@{harness_remote.old} # v0.3.0"


def test_init_with_an_unresolved_ref_writes_nothing(target: Path, harness_remote: HarnessRemote, capsys):
    flags = ("--action", "--action-repo", "o/harness", "--harness-ref", "v7")
    assert init(target, harness_remote.environ, *flags) == 2
    assert "v7" in capsys.readouterr().err
    assert not (target / ".l4").exists() and not (target / ".github").exists()


def test_upgrade_by_version_rewrites_only_the_uses_line(target: Path, harness_remote: HarnessRemote):
    """SCN-ACT-10: `l4 upgrade --harness-ref v0.4.0` moves the pin and nothing else."""
    adopt(target, harness_remote)
    before = (target / WORKFLOW).read_text()
    config = (target / ".l4/config.yaml").read_text()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 0
    after = (target / WORKFLOW).read_text()
    assert changed_lines(before, after) == [
        (
            f"        uses: o/harness/.github/actions/l4@{harness_remote.old} # v0.3.0",
            f"        uses: o/harness/.github/actions/l4@{harness_remote.new} # v0.4.0",
        )
    ]
    assert (target / ".l4/config.yaml").read_text() == config
    assert not (target / ".l4/bin").exists() and not (target / ".l4/vendor").exists()


def test_upgrade_by_commit_drops_the_stale_ref_comment(target: Path, harness_remote: HarnessRemote):
    adopt(target, harness_remote)
    assert upgrade(target, harness_remote.environ, "--harness-commit", SHA) == 0
    assert uses_line(target) == f"uses: o/harness/.github/actions/l4@{SHA}"


def test_upgrade_in_copy_mode_rewrites_only_the_commit_input(target: Path, harness_remote: HarnessRemote, copy_harness):
    flags = ("--action", "--action-copy", "--harness", str(copy_harness), "--action-repo", "o/harness")
    assert init(target, harness_remote.environ, *flags, "--harness-ref", "v0.3.0") == 0
    before = (target / WORKFLOW).read_text()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 0
    after = (target / WORKFLOW).read_text()
    assert changed_lines(before, after) == [
        (f'          commit: "{harness_remote.old}"', f'          commit: "{harness_remote.new}"')
    ]
    assert yaml.safe_load(after)["jobs"]["l4"]["steps"][2]["uses"] == "./.github/actions/l4"


def test_upgrade_needs_exactly_one_of_ref_and_commit(target: Path, harness_remote: HarnessRemote, capsys):
    adopt(target, harness_remote)
    before = (target / WORKFLOW).read_text()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0", "--harness-commit", SHA) == 2
    assert "exclude each other" in capsys.readouterr().err
    assert (target / WORKFLOW).read_text() == before


def test_upgrade_with_an_unresolved_ref_changes_nothing(target: Path, harness_remote: HarnessRemote, capsys):
    adopt(target, harness_remote)
    before = (target / WORKFLOW).read_text()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v8") == 2
    assert "v8" in capsys.readouterr().err and (target / WORKFLOW).read_text() == before


def test_upgrade_refuses_a_workflow_with_no_uses_line_to_move(target: Path, harness_remote: HarnessRemote, capsys):
    adopt(target, harness_remote)
    (target / WORKFLOW).write_text("name: l4\n")
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 2
    assert "uses:" in capsys.readouterr().err


def test_fetched_init_and_upgrade_take_a_ref_too(target: Path, harness_remote: HarnessRemote):
    """The ref resolves the commit that `harness.commit` pins; nothing else about the fetched form changes."""
    assert init(target, harness_remote.environ, "--harness-repo", harness_remote.URL, "--harness-ref", "v0.3.0") == 0
    assert yaml.safe_load((target / ".l4/config.yaml").read_text())["harness"]["commit"] == harness_remote.old
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 0
    assert yaml.safe_load((target / ".l4/config.yaml").read_text())["harness"]["commit"] == harness_remote.new


def test_a_vendored_adoption_has_no_ref_to_move(target: Path, harness_repo: Path, harness_remote, capsys):
    flags = ("--vendor", "--harness", str(harness_repo), "--harness-ref", "v0.3.0")
    assert init(target, harness_remote.environ, *flags) == 2
    assert "--harness-ref" in capsys.readouterr().err


def test_ref_and_commit_exclude_each_other_on_init(target: Path, harness_remote: HarnessRemote, capsys):
    flags = ("--action", "--action-repo", "o/harness", "--harness-ref", "v0.3.0", "--harness-commit", SHA)
    assert init(target, harness_remote.environ, *flags) == 2
    assert "exclude each other" in capsys.readouterr().err


OLD_SAVE_PATHS = """\
          path: |
            ~/.local/bin
            !~/.local/bin/uv
            !~/.local/bin/uvx
            !~/.local/bin/l4
            ~/.local/share/l4
            ~/.local/share/claude
            ~/.cache/l4/installers
"""
NEW_SAVE_PATH = "          path: ${{ steps.l4.outputs.clis-cache-paths }}\n"


def adopt_hosted(target: Path, remote: HarnessRemote) -> None:
    """An adoption, then its workflow in the hosted-runner form (the only one with a save step)."""
    adopt(target, remote)
    pin = ActionPin(repository="o/harness", sha=remote.old, ref="v0.3.0")
    hosted = render_github_action_ci(L4Config.model_validate({"ci": {"runner_tags": []}}), pin)
    (target / WORKFLOW).write_text(hosted)


def test_upgrade_replaces_a_literal_save_path_block_once(target: Path, harness_remote: HarnessRemote, capsys):
    """L4-ACT-002: an adoption made before the paths became an action output keeps its literal list; the upgrade moves
    the pin and swaps that one block, nothing else, and says so."""
    adopt_hosted(target, harness_remote)
    current = (target / WORKFLOW).read_text()
    assert NEW_SAVE_PATH in current and OLD_SAVE_PATHS.count("\n") == 8
    old = current.replace(NEW_SAVE_PATH, OLD_SAVE_PATHS)
    (target / WORKFLOW).write_text(old)
    capsys.readouterr()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 0
    out = capsys.readouterr().out
    new = (target / WORKFLOW).read_text()
    assert new == current.replace(f"@{harness_remote.old} # v0.3.0", f"@{harness_remote.new} # v0.4.0")
    assert out.count("clis-cache-paths") == 1 and "save agent CLI cache" in out
    assert upgrade(target, harness_remote.environ, "--harness-commit", SHA) == 0  # the second time: only the pin
    assert "clis-cache-paths" not in capsys.readouterr().out


def test_upgrade_keeps_a_new_form_workflow_to_the_uses_line(target: Path, harness_remote: HarnessRemote, capsys):
    adopt_hosted(target, harness_remote)
    before = (target / WORKFLOW).read_text()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0") == 0
    assert len(changed_lines(before, (target / WORKFLOW).read_text())) == 1
    assert "clis-cache-paths" not in capsys.readouterr().out


def test_dry_run_reports_the_save_migration_and_writes_nothing(target: Path, harness_remote: HarnessRemote, capsys):
    adopt_hosted(target, harness_remote)
    old = (target / WORKFLOW).read_text().replace(NEW_SAVE_PATH, OLD_SAVE_PATHS)
    (target / WORKFLOW).write_text(old)
    capsys.readouterr()
    assert upgrade(target, harness_remote.environ, "--harness-ref", "v0.4.0", "--dry-run") == 0
    assert "would change" in capsys.readouterr().out
    assert (target / WORKFLOW).read_text() == old
