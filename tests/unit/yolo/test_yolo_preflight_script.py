"""`scripts/yolo_preflight.py` (yolo-guardrails D10; L4-SKL-005; SCN-SKL-11 to -15): twelve checks and one `Next:` line,
run against a scratch repository with a bare origin and fake `l4`, `opencode` and `claude` programs."""

import ast
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config_text

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "l4" / "skills" / "l4" / "scripts" / "yolo_preflight.py"
UNIT = "openspec:add-greeting"
FOLDER = "openspec/changes/add-greeting"
PLAN = {
    "schema": "l4/delivery-plan@1",
    "plan_id": "p1",
    "target": "main",
    "merge": "human",
    "batches": [{"id": "b1", "units": [{"id": UNIT, "depends_on": []}]}],
}
CONFIG = """\
forge:
  base_branch: main
profiles:
  claude:
    adapter: claude-code
  oc:
    adapter: opencode
roles:
  implementer:
    - oc
  judges:
    - claude
yolo:
  review:
    accept_by_agents: false
"""


def load_module():
    spec = importlib.util.spec_from_file_location("yolo_preflight_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pf = load_module()


def status_doc(**plan) -> dict:
    body = {
        "plan_id": "p1",
        "status": "admitted",
        "review": {"state": "none", "problems": [], "accepted": []},
        "next": "l4 yolo review p1",
    }
    body.update(plan)
    return {"schema": "l4/yolo-status@1", "target": "main", "plans": [body]}


def tool(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.fake = tmp_path / "fake"
        self.bin.mkdir()
        self.fake.mkdir()
        git_dir = str(Path(shutil.which("git") or "/usr/bin/git").parent)
        self.env = {
            "PATH": f"{self.bin}:{git_dir}",
            "HOME": str(tmp_path / "home"),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.origin = tmp_path / "origin.git"
        self.repo = tmp_path / "repo"
        self.git("init", "--quiet", "--bare", "-b", "main", str(self.origin), cwd=tmp_path)
        self.git("clone", "--quiet", str(self.origin), str(self.repo), cwd=tmp_path)
        self.git("checkout", "-q", "-b", "main")
        self.write(".l4/config.yaml", CONFIG)
        self.write(".l4/plans/p1.json", json.dumps(PLAN, indent=2))
        self.write(f"{FOLDER}/proposal.md", "# p\n")
        self.write(f"{FOLDER}/tasks.md", "- [ ] 1.1 x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.git("push", "-q", "origin", "HEAD:main")
        self.set_status(status_doc())
        self.set_findings({"schema": "l4/yolo-findings@1", "plan": "p1", "base": "main", "subjects": []})
        self.set_check(0)
        self.fake_l4()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True, check=True
        )
        return done.stdout

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, rel: str, text: str, *, push: bool = False) -> None:
        self.write(rel, text)
        self.git("add", rel)
        self.git("commit", "-q", "-m", f"edit {rel}")
        if push:
            self.git("push", "-q", "origin", "HEAD:main")

    def set_status(self, doc: dict) -> None:
        (self.fake / "status.json").write_text(json.dumps(doc), encoding="utf-8")

    def set_findings(self, doc: dict) -> None:
        (self.fake / "findings.json").write_text(json.dumps(doc), encoding="utf-8")

    def set_check(self, code: int, text: str = "") -> None:
        (self.fake / "check_exit").write_text(str(code), encoding="utf-8")
        (self.fake / "check_out").write_text(text, encoding="utf-8")

    def fake_l4(self) -> None:
        tool(
            self.bin / "l4",
            f"""import pathlib, sys
fake = pathlib.Path({str(self.fake)!r})
with (fake / "calls.log").open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args == ["--version"]:
    print("l4 0.4.18")
elif args[:2] == ["yolo", "check"]:
    print((fake / "check_out").read_text())
    sys.exit(int((fake / "check_exit").read_text()))
elif args[:2] == ["yolo", "status"]:
    print((fake / "status.json").read_text())
elif args[:2] == ["yolo", "findings"]:
    print((fake / "findings.json").read_text())
else:
    sys.exit(3)
""",
        )

    def calls(self) -> list[str]:
        path = self.fake / "calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def opencode(self, version: str = "1.18.34") -> None:
        tool(self.bin / "opencode", f"print({version!r})\n")

    def claude(self) -> None:
        tool(self.bin / "claude", "print('claude')\n")

    def run(self, *argv: str, env: dict | None = None):
        done = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "p1", "--repo", str(self.repo), *argv],
            capture_output=True,
            text=True,
            env={**self.env, **(env or {})},
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        return done.returncode, done.stdout, done.stderr

    def next(self, out: str) -> str:
        lines = [ln for ln in out.splitlines() if ln.startswith("Next:")]
        assert len(lines) == 1, out
        return lines[0].removeprefix("Next: ")


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.opencode()
    w.claude()
    return w


def result_of(out: str, name: str) -> str:
    line = next(ln for ln in out.splitlines() if f"  {name}:" in ln)
    return line.split()[0]


def test_the_script_needs_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_the_constants_equal_the_harness():
    from l4.actor import AGENT_MARKERS
    from l4.config import roles
    from l4.provision import catalog

    assert tuple(pf.JUDGE_ADAPTERS) == roles.JUDGE_ADAPTERS
    assert tuple(pf.JUDGE_ROLES) == roles.JUDGE_ROLES
    assert tuple(pf.HARNESS_ADAPTERS) == roles.HARNESS_ADAPTERS
    assert tuple(pf.AGENT_MARKERS) == AGENT_MARKERS
    assert pf.OPENCODE_PIN == catalog.OPENCODE_VERSION
    assert catalog.SUPPORTED_MAJORS["opencode"] == pf.OPENCODE_MAJOR


def test_a_pushed_admitted_plan_with_no_review_gets_the_review_command(world):
    code, out, _ = world.run()
    assert code == 0
    assert all(
        result_of(out, n) != "FAIL" for n in ("plan-file", "clean-tree", "origin", "head-is-origin", "on-origin")
    )
    assert world.next(out) == "l4 yolo review p1 --worktree --record"
    (world.bin / "claude").unlink()
    code, out, _ = world.run()
    assert code == 0
    assert world.next(out) == ("l4 yolo review p1 (CI reviews origin/main at its next run; then run this script again)")


def test_a_dirty_tree_fails_with_its_fix(world):
    world.write(f"{FOLDER}/notes.md", "new\n")
    code, out, _ = world.run()
    assert code == 1
    assert result_of(out, "clean-tree") == "FAIL" and f"{FOLDER}/notes.md" in out
    assert world.next(out) == "commit the changes git status lists, then git push origin HEAD:main"
    assert world.calls() == []


def test_an_unpushed_commit_fails_with_the_push(world):
    world.commit(f"{FOLDER}/proposal.md", "# changed\n")
    code, out, _ = world.run()
    assert code == 1
    assert result_of(out, "head-is-origin") == "FAIL" and "is 1 commit behind HEAD" in out
    assert world.next(out) == "git push origin HEAD:main, then run this script again"
    assert world.calls() == []


def test_a_plan_that_is_not_on_origin_names_the_first_missing_path(world):
    world.write(
        ".l4/plans/p1.json", json.dumps({**PLAN, "batches": [{"id": "b1", "units": [{"id": "openspec:other"}]}]})
    )
    world.git("add", "-A")
    world.git("commit", "-q", "-m", "other unit")
    world.git("push", "-q", "origin", "HEAD:main")
    code, out, _ = world.run()
    assert code == 1 and result_of(out, "on-origin") == "FAIL"
    assert world.next(out) == "commit and push openspec/changes/other, then run this script again"


def test_a_command_judge_fails_with_the_harness_text(world):
    config = CONFIG.replace(
        "  oc:\n    adapter: opencode\n", "  cmd:\n    adapter: command\n    options:\n      argv:\n        - tool\n"
    ).replace(
        "  implementer:\n    - oc\n  judges:\n    - claude",
        "  implementer:\n    - claude\n  judges:\n    - cmd\n    - claude",
    )
    world.commit(".l4/config.yaml", config, push=True)
    with pytest.raises(ConfigSchemaError) as err:
        load_config_text(config)
    expected = str(err.value).removesuffix(" at $")
    code, out, _ = world.run("--json")
    doc = json.loads(out)
    judge = next(c for c in doc["checks"] if c["name"] == "judge-roles")
    assert code == 1 and judge["result"] == "FAIL" and judge["detail"] == expected
    assert doc["next"] == "remove cmd from roles.judges in .l4/config.yaml, commit and push, then run this script again"
    assert world.calls() == []


def test_an_opencode_v2_fails(world):
    world.opencode("opencode v2.0.32")
    code, out, _ = world.run()
    assert code == 1 and result_of(out, "opencode") == "FAIL"
    assert "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x)" in out
    assert world.next(out) == (
        "l4 doctor --fix (it installs opencode-ai@1.18.34 user-locally), then run this script again"
    )


@pytest.mark.parametrize("printed", ["1.18.34", "opencode v1.18.34"])
def test_an_opencode_v1_passes_both_version_forms(world, printed):
    world.opencode(printed)
    code, out, _ = world.run()
    assert code == 0 and result_of(out, "opencode") == "ok"


def ready_review(world, problems=()):
    world.set_status(
        status_doc(review={"state": "current", "problems": list(problems), "accepted": []}, next="l4 yolo activate p1")
    )


def test_an_agent_with_a_ready_review_hands_activation_to_a_person(world):
    ready_review(world)
    code, out, _ = world.run(env={"CLAUDECODE": "1"})
    assert code == 0 and result_of(out, "caller") == "info" and "agent (CLAUDECODE)" in out
    assert world.next(out) == (
        'a person runs: l4 yolo activate p1 --reason "<why>" (stop here: activation is a person\'s decision)'
    )


def test_a_person_is_told_to_activate(world, monkeypatch, capsys):
    ready_review(world)
    monkeypatch.setattr(pf, "stdin_is_tty", lambda: True)
    env = dict(world.env)
    assert pf.main(["p1", "--repo", str(world.repo)], environ=env) == 0
    out = capsys.readouterr().out
    assert "person" in out and world.next(out) == 'l4 yolo activate p1 --reason "<why>"'


NOT_READY = f"{UNIT}: NEEDS_REVISION: testability: no inputs"


def findings(**subject) -> dict:
    row = {
        "subject": UNIT,
        "verdict": "NEEDS_REVISION",
        "persistent": {},
        "accepted": None,
        "accept_available": False,
        "accept_refusal": None,
    }
    row.update(subject)
    return {"schema": "l4/yolo-findings@1", "plan": "p1", "base": "main", "subjects": [row]}


AGENT_ACCEPTS = CONFIG.replace("accept_by_agents: false", "accept_by_agents: true")


@pytest.mark.parametrize("env", [{}, {"CLAUDECODE": "1"}])
def test_a_subject_past_two_rounds_is_accepted_by_an_agent_with_yes(world, env):
    """SCN-SKL-15: with `accept_by_agents` an agent (no terminal on stdin, or a marker) is told to accept with --yes."""
    world.commit(".l4/config.yaml", AGENT_ACCEPTS, push=True)
    ready_review(world, [NOT_READY])
    world.set_findings(findings(accept_available=True))
    code, out, _ = world.run(env=env)
    assert code == 0
    assert world.next(out) == f'l4 yolo accept p1 {UNIT} --reason "<what the implementer should do>" --yes'


def test_an_agent_is_not_told_to_accept_when_origin_does_not_let_agents(world):
    ready_review(world, [NOT_READY])
    world.set_findings(findings(accept_available=True))  # the harness answer cannot override the config at origin
    _, out, _ = world.run(env={"CLAUDECODE": "1"})
    assert "accept" not in world.next(out).split()[2]


@pytest.mark.parametrize(
    "row",
    [
        {"accept_available": True},
        {"accept_refusal": {"why": "acceptance is a person's decision", "fix": "a person runs: l4 yolo accept p1 x"}},
    ],
)
def test_a_person_is_told_to_accept_under_the_normal_rules(world, monkeypatch, capsys, row):
    """The findings run has no terminal, so it always answers as an agent: a person's availability is derived from
    the caller kind, and the agent-only refusal does not apply to a person."""
    ready_review(world, [NOT_READY])
    world.set_findings(findings(**row))
    monkeypatch.setattr(pf, "stdin_is_tty", lambda: True)
    assert pf.main(["p1", "--repo", str(world.repo)], environ=dict(world.env)) == 0
    assert (
        world.next(capsys.readouterr().out) == f'l4 yolo accept p1 {UNIT} --reason "<what the implementer should do>"'
    )


def test_a_person_is_not_told_to_accept_past_another_refusal(world, monkeypatch, capsys):
    ready_review(world, [NOT_READY])
    world.set_findings(findings(accept_refusal={"why": "was judged not READY on 1 version", "fix": "change the spec"}))
    monkeypatch.setattr(pf, "stdin_is_tty", lambda: True)
    assert pf.main(["p1", "--repo", str(world.repo)], environ=dict(world.env)) == 0
    assert " accept " not in world.next(capsys.readouterr().out)


def test_a_persistent_blocking_finding_goes_to_a_person(world):
    ready_review(world, [NOT_READY])
    world.set_findings(
        findings(persistent={"testability": 2}, accept_refusal={"why": "BLOCKED", "fix": "fix the spec"})
    )
    _, out, _ = world.run()
    assert world.next(out) == (
        f"a person decides {UNIT}: l4 yolo findings p1 {UNIT} (the finding came back after a spec fix and cannot be "
        "accepted; stop here)"
    )
    world.set_findings(
        findings(accept_refusal={"why": "an agent may not", "fix": 'a person runs: l4 yolo accept p1 x --reason "..."'})
    )
    _, out, _ = world.run()
    assert world.next(out) == 'a person runs: l4 yolo accept p1 x --reason "..." (stop here)'
    world.set_findings(findings())
    _, out, _ = world.run()
    assert world.next(out) == (
        f"l4 yolo findings p1 {UNIT}, fix the spec as its Resolve: lines say, commit and push, then run this script "
        "again"
    )


def test_an_active_plan_prints_the_status_next_line(world):
    world.set_status(status_doc(status="active", next="l4 yolo status p1 shows the run: wait for CI"))
    code, out, _ = world.run()
    assert code == 0 and world.next(out) == "l4 yolo status p1 shows the run: wait for CI"


def test_an_admission_failure_names_its_first_line(world):
    world.set_check(2, "unknown_unit: openspec:ghost is not a unit\nmore\n")
    code, out, _ = world.run()
    assert code == 1 and result_of(out, "admission") == "FAIL" and "unknown_unit: openspec:ghost" in out
    assert world.next(out) == "l4 yolo check p1: fix what it prints, commit and push, then run this script again"


def test_json_output(world):
    code, out, _ = world.run("--json")
    doc = json.loads(out)
    assert code == 0 and doc["schema"] == "l4/yolo-preflight@1" and doc["plan"] == "p1" and doc["base"] == "main"
    assert doc["exit"] == 0 and doc["next"] == "l4 yolo review p1 --worktree --record"
    assert doc["caller"]["kind"] == "agent"
    assert [c["name"] for c in doc["checks"]] == [
        "plan-file", "clean-tree", "origin", "head-is-origin", "on-origin", "judge-roles", "opencode",
        "accept-by-agents", "caller", "harness", "admission", "review",
    ]  # fmt: skip
    assert {c["result"] for c in doc["checks"]} <= {"ok", "FAIL", "skip", "info"}
    world.write(f"{FOLDER}/notes.md", "new\n")
    code, out, _ = world.run("--json")
    failed = json.loads(out)
    assert code == 1 and failed["exit"] == 1 and failed["next"]
    assert {c["name"]: c["result"] for c in failed["checks"]}["harness"] == "skip"


def test_a_hanging_opencode_is_bounded(world):
    tool(world.bin / "opencode", "import time\ntime.sleep(60)\n")
    started = time.monotonic()
    code, out, _ = world.run()
    assert time.monotonic() - started < 40
    assert code == 1 and result_of(out, "opencode") == "FAIL"
    assert world.next(out) == "l4 doctor"


def test_a_bad_plan_id_is_a_usage_error(world):
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "Bad_Id", "--repo", str(world.repo)],
        capture_output=True, text=True, env=world.env, timeout=60, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert done.returncode == 2 and "not a plan id" in done.stderr
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "p1", "--repo", str(world.root)],
        capture_output=True, text=True, env=world.env, timeout=60, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert done.returncode == 2 and "not a git work tree" in done.stderr


# --- force acceptance, agent wrapper and the --l4 text (review findings MAJOR-2, MINOR-3, MINOR-10) ---

WRAP_TAIL = " (stop here: activation is a person's decision)"


def force_review(world, state="none", problems=(), covered=True):
    world.set_status(
        status_doc(
            review={
                "state": state,
                "problems": list(problems),
                "accepted": [],
                "force_accepted": {"covered": covered},
            },
            next="l4 yolo activate p1 --reason TEXT" if covered and not problems else "l4 yolo findings p1: fix",
        )
    )


@pytest.mark.parametrize("state", ["none", "stale"])
def test_a_force_accepted_plan_gets_the_activate_line(world, monkeypatch, capsys, state):
    force_review(world, state)
    code, out, _ = world.run(env={"CLAUDECODE": "1"})
    assert code == 0
    assert world.next(out) == f'a person runs: l4 yolo activate p1 --reason "<why>"{WRAP_TAIL}'
    monkeypatch.setattr(pf, "stdin_is_tty", lambda: True)
    assert pf.main(["p1", "--repo", str(world.repo)], environ=dict(world.env)) == 0
    assert world.next(capsys.readouterr().out) == 'l4 yolo activate p1 --reason "<why>"'


def test_a_force_accepted_plan_with_current_problems_is_not_sent_to_activate(world):
    force_review(world, "current", [NOT_READY])
    _, out, _ = world.run()
    assert "activate" not in world.next(out)


def test_an_agent_is_never_given_an_activate_or_force_line_unwrapped(world):
    world.set_status(
        status_doc(
            status="stopped", stop={"reason": "unit_rejected"},
            next="fix the cause of the rejection of u, then l4 yolo activate p1 --reason TEXT",
        )
    )  # fmt: skip
    _, out, _ = world.run(env={"CLAUDECODE": "1"})
    line = world.next(out)
    assert line.startswith("a person runs: fix the cause") and line.endswith(WRAP_TAIL)
    world.set_status(
        status_doc(status="stopped", stop={"reason": "x"}, next="a person runs l4 yolo accept p1 --all --force")
    )
    _, out, _ = world.run(env={"CLAUDECODE": "1"})
    assert world.next(out).endswith(WRAP_TAIL)
    world.set_status(status_doc(status="active", next="l4 yolo status p1 shows the run"))
    _, out, _ = world.run(env={"CLAUDECODE": "1"})
    assert world.next(out) == "l4 yolo status p1 shows the run"


def test_every_next_line_uses_the_l4_command_text(world):
    shutil.copy(world.bin / "l4", world.bin / "l4x")
    (world.repo / ".l4" / "plans" / "p1.json").rename(world.repo / ".l4" / "plans" / "other.json")
    _, out, _ = world.run("--l4", "l4x")
    assert world.next(out) == "l4x yolo draft p1"
    (world.repo / ".l4" / "plans" / "other.json").rename(world.repo / ".l4" / "plans" / "p1.json")
    world.opencode("opencode v2.0.32")
    _, out, _ = world.run("--l4", "l4x")
    assert world.next(out).startswith("l4x doctor --fix (it installs")
    world.opencode()
    world.set_status(status_doc(status="active", next="l4 yolo status p1 shows the run: wait for CI"))
    _, out, _ = world.run("--l4", "l4x")
    assert world.next(out) == "l4x yolo status p1 shows the run: wait for CI"
    ready_review(world, [NOT_READY])
    world.set_findings(
        findings(accept_refusal={"why": "x", "fix": 'a person runs: l4 yolo accept p1 x --reason "..."'})
    )
    _, out, _ = world.run("--l4", "l4x")
    assert world.next(out) == 'a person runs: l4x yolo accept p1 x --reason "..." (stop here)'


def test_a_child_that_exited_before_the_deadline_is_not_a_timeout(tmp_path):
    body = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print('1.18.34', flush=True)\n"
    )
    script = tmp_path / "child.py"
    script.write_text(body, encoding="utf-8")
    started = time.monotonic()
    code, out, _ = pf.run([sys.executable, str(script)], tmp_path, 1.0)
    assert (code, out) == (0, "1.18.34\n") and time.monotonic() - started < 2.5
