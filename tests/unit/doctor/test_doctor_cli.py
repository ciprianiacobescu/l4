"""End to end through `main()`: real `which`/`run` against fake tools on a private PATH."""

import json
import stat
from pathlib import Path

import pytest

from l4.cli import main
from l4.config.defaults import openspec_entrypoint

FAKE_NODE = """#!/bin/sh
case "$*" in
  *openspec.js*) echo 1.14.0 ;;
  *) echo v22.22.0 ;;
esac
"""


VALID_CONFIG = """\
profiles:
  impl: {adapter: fake, vendor: a}
  judge: {adapter: fake, vendor: b}
roles: {implementer: [impl], judges: [judge]}
gates: {test: {command: pytest -q}}
"""


def fake_tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # the root prerequisites (bubblewrap is Linux only) are the machine's business, not these tests': the same
    # report on a Mac and on a Linux runner
    monkeypatch.setattr("l4.doctor.checks_provision.detect_platform", lambda: "darwin-arm64")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_tool(bin_dir, "git", '#!/bin/sh\necho "git version 2.43.0"\n')
    fake_tool(bin_dir, "uv", '#!/bin/sh\necho "uv 0.10.0"\n')
    fake_tool(bin_dir, "node", FAKE_NODE)
    fake_tool(bin_dir, "serena", '#!/bin/sh\necho "1.7.0"\n')  # ENV-008: Serena is on by default
    repo = tmp_path / "repo"
    (repo / "openspec" / "changes").mkdir(parents=True)  # SPEC-001: an empty openspec/ is no framework
    environ = {"PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "L4_HOME": str(tmp_path / "l4home")}
    js = openspec_entrypoint(environ)
    js.parent.mkdir(parents=True)
    js.write_text("// fake openspec", encoding="utf-8")
    write_config(repo, VALID_CONFIG)
    return repo, environ, bin_dir


def write_config(repo: Path, text: str) -> None:
    (repo / ".l4").mkdir(exist_ok=True)
    (repo / ".l4" / "config.yaml").write_text(text, encoding="utf-8")


def test_doctor_end_to_end_exit_codes(world, capsys):
    repo, environ, bin_dir = world
    # healthy: exit 0, no outcome.json (doctor is not an outcome command)
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 0
    out = capsys.readouterr().out
    assert "ENV-001" in out and "ENV-002" in out and "ENV-003" in out and "fail" not in out
    assert not (repo / ".l4-out").exists()
    # a mistyped key: exit 2 with the did-you-mean message, no checks run
    write_config(repo, "verifer: {independence: none}\n")
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 2
    captured = capsys.readouterr()
    assert "unknown key 'verifer' at $ (did you mean 'verifier'?)" in captured.err
    assert "ENV-001" not in captured.out
    # a failing error check: exit 3 (secret-in-config CFG-001 is deferred, see m0-progress)
    write_config(repo, VALID_CONFIG)
    (bin_dir / "uv").unlink()
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    assert "uv" in capsys.readouterr().out


def test_json_output_and_resolved_paths(world, capsys):
    repo, environ, _ = world
    environ = {**environ, "L4_CACHE": str(repo.parent / "cache")}
    assert main(["doctor", "--json", "--repo", str(repo)], environ=environ) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "l4/doctor@1" and doc["ok"] is True and doc["exit_code"] == 0
    ids = [c["id"] for c in doc["checks"]]
    expected = ["CI-001", "CFG-002", "ENV-001", "ENV-002", "ENV-003", "ENV-004", "PRV-001", "PRV-002"]
    expected += ["SPEC-001", "SPEC-002", "SPEC-004", "MEM-001", "ENV-006", "ENV-007", "ENV-008"]
    expected += ["S1-001", "S1-002", "COV-001", "SANDBOX-002", "CFG-005", "MEM-002", "CI-002", "ENV-013", "EVAL-001"]
    expected += ["ENV-014", "CFG-004", "CFG-006", "CFG-007", "YOLO-001", "CI-003"]
    assert sorted(ids) == sorted(expected)  # registration order follows the import order of the check modules
    skipped = {
        "CI-001",
        "CI-002",
        "ENV-004",
        "PRV-001",
        "SPEC-002",
        "SPEC-004",
        "ENV-006",
        "ENV-007",
    }  # not GitLab; no agent CLI
    skipped |= {"CFG-006", "CFG-007"}  # not an action adoption
    skipped |= {"YOLO-001", "CI-003"}  # merge_policy is human; no CI file
    skipped |= {"S1-001", "S1-002", "COV-001", "ENV-013", "EVAL-001"}  # nothing shadowed, no tuned checkpoint or
    # Ollama host, no project interpreter, no eval baseline in this repository
    # profile; no Kiro; no Laya profile, no e2e gate
    host = {"PRV-002", "SANDBOX-002"}  # bubblewrap on the machine running the tests: not this test's business
    assert {c["status"] for c in doc["checks"] if c["id"] not in skipped | host} == {"pass"}
    assert {c["id"] for c in doc["checks"] if c["status"] == "skip"} - host == skipped
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 0
    table = capsys.readouterr().out
    assert str(repo.parent / "cache") in table and environ["L4_HOME"] in table


def test_cache_inside_repo_is_a_usage_error(world, capsys):
    repo, environ, _ = world
    environ = {**environ, "L4_CACHE": str(repo / ".l4-cache")}
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 2
    assert "L4_CACHE" in capsys.readouterr().err
    assert not (repo / ".l4-cache").exists()


def test_fix_with_nothing_failing_applies_nothing(world, capsys):
    """It reports what is in place or missing (`already present`, `planned`), and installs nothing."""
    repo, environ, _ = world
    assert main(["doctor", "--fix", "--repo", str(repo)], environ=environ) == 0
    out = capsys.readouterr().out
    assert "\nfix " in out and "applied" not in out and "failed" not in out  # the fake tools are not the pinned ones


def test_fix_on_a_provisioned_runner_lists_every_tool_as_already_present(world, capsys):
    """The live check 'fix2': nothing failed, so nothing is installed, and the actions say why."""
    from l4.provision.catalog import UV_VERSION

    repo, environ, bin_dir = world
    fake_tool(bin_dir, "uv", f'#!/bin/sh\necho "uv {UV_VERSION}"\n')
    Path(environ["HOME"]).mkdir()  # the version probes run in it
    assert main(["doctor", "--ci", "--fix", "--json", "--repo", str(repo)], environ=environ) == 0
    fixes = json.loads(capsys.readouterr().out)["fixes"]
    assert fixes and {f["tool"] for f in fixes} >= {"uv", "node", "openspec"}
    assert all(f["status"] == "already present" for f in fixes), fixes


def test_ci_unit_and_live_flags_are_accepted(world):
    repo, environ, _ = world
    (repo / "openspec" / "changes" / "x").mkdir()
    (repo / "openspec" / "changes" / "x" / "tasks.md").write_text("- [ ] 1.1 a\n")
    assert main(["doctor", "--ci", "--unit", "openspec:x", "--live", "--repo", str(repo)], environ=environ) == 0


def test_openspec_check_fails_closed_when_prefix_absent(world, capsys):
    repo, environ, _ = world
    environ = {**environ, "L4_HOME": str(repo.parent / "empty-home")}
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    assert "ENV-003" in capsys.readouterr().out


def test_secret_in_environment_never_printed(world, capsys):
    """The secret is the offending key name, which the error message prints: only the redactor can hide it."""
    repo, environ, _ = world
    token = "forge-token-value-9999"
    write_config(repo, f"{token}: 1\n")
    assert main(["doctor", "--repo", str(repo)], environ={**environ, "L4_FORGE_TOKEN": token}) == 2
    captured = capsys.readouterr()
    assert "unknown key" in captured.err and "[REDACTED" in captured.err
    assert token not in captured.out + captured.err


def test_misspelled_role_profile_fails_cfg_002(world, capsys):
    repo, environ, bin_dir = world
    write_config(repo, "profiles: {claude-code: {adapter: claude-code}}\nroles: {judges: [claude-cod]}\n")
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    out = capsys.readouterr().out
    assert "CFG-002" in out and "roles.judges" in out
    write_config(
        repo,
        "profiles: {claude-code: {adapter: claude-code}}\nroles: {implementer: [claude-code], judges: [claude-code]}\n"
        "gates: {test: {command: pytest -q}}\n",
    )
    fake_tool(bin_dir, "claude", '#!/bin/sh\necho "2.1.288 (Claude Code)"\n')  # ENV-004: the profile's CLI exists
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 0


def test_profile_with_adapter_and_backend_fails_cfg_002(world, capsys):
    repo, environ, _ = world
    write_config(repo, "profiles: {p: {adapter: a, backend: b}}\n")
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    assert "profiles.p" in capsys.readouterr().out


def test_doctor_stdout_is_redacted(world, capsys):
    """The cache path is printed; a secret inside it must not reach stdout."""
    repo, environ, _ = world
    token = "tok-secretvalue-9999"
    environ = {**environ, "L4_CACHE": str(repo.parent / token), "L4_FORGE_TOKEN": token}
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 0
    out = capsys.readouterr().out
    assert token not in out and "[REDACTED:L4_FORGE_TOKEN]" in out


@pytest.mark.parametrize("empty", ["implementer", "judges"])
def test_empty_required_role_fails_cfg_002(world, capsys, empty):
    repo, environ, _ = world
    other = "judges" if empty == "implementer" else "implementer"
    write_config(repo, f"profiles: {{p: {{adapter: fake}}}}\nroles: {{{other}: [p]}}\n")
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    out = capsys.readouterr().out
    assert "CFG-002" in out and f"roles.{empty} is empty" in out


def test_no_config_at_all_fails_cfg_002(world, capsys):
    repo, environ, _ = world
    (repo / ".l4" / "config.yaml").unlink()
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    assert "roles.implementer is empty" in capsys.readouterr().out


def test_a_unit_that_names_nothing_is_a_usage_error_not_a_passing_run(world, capsys):
    repo, environ, _ = world
    (repo / "openspec" / "changes" / "add-x").mkdir()
    (repo / "openspec" / "changes" / "add-x" / "tasks.md").write_text("- [ ] 1.1 a\n")
    assert main(["doctor", "--unit", "openspec:nope", "--repo", str(repo)], environ=environ) == 2
    assert "no such unit: openspec:nope" in capsys.readouterr().err
    assert main(["doctor", "--unit", "openspec:add-x", "--repo", str(repo)], environ=environ) == 0


def test_adoption_without_agent_clis_exits_0(world, capsys):
    """A4 (M1.8): on a laptop with no `codex`, `doctor --adoption --no-gates` looks at the repository only; the plain
    doctor fails ENV-004 for the same repository."""
    repo, environ, _ = world
    write_config(
        repo,
        "profiles:\n  impl: {adapter: codex, vendor: openai}\n  judge: {adapter: claude-code, vendor: anthropic}\n"
        "roles: {implementer: [impl], judges: [judge]}\ngates: {test: {command: pytest -q}}\n",
    )
    assert main(["doctor", "--repo", str(repo)], environ=environ) == 3
    assert "ENV-004" in capsys.readouterr().out
    assert main(["doctor", "--adoption", "--no-gates", "--json", "--repo", str(repo)], environ=environ) == 0
    ids = {c["id"] for c in json.loads(capsys.readouterr().out)["checks"]}
    assert {"CFG-002", "SPEC-001"} <= ids
    assert not {i for i in ids if i.startswith(("ENV-", "PRV-", "SANDBOX-", "COV-", "LIVE-", "S1-"))}


def test_no_gates_without_adoption_is_a_usage_error(world, capsys):
    repo, environ, _ = world
    assert main(["doctor", "--no-gates", "--repo", str(repo)], environ=environ) == 2
    assert "--no-gates" in capsys.readouterr().err
