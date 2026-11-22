"""L4-OPS-026: an `l4` older than the repository's pin does not write for it by accident (SCN-OPS-56 to -62).

The repository is a temporary git repository; the pin is a `harness.version` or the `# vX.Y.Z` comment of the setup
action's `uses:` line, at `refs/remotes/origin/main` (made with `git update-ref`: no fetch, no network) or in the
working tree. `FAKE_DISPATCH` stands in for every command handler, so a refused command is one the handler never saw."""

import json
import subprocess
from pathlib import Path

import pytest

from l4 import cli_pin
from l4.cli import main
from l4.commands import HANDLERS
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult

SHA = "a" * 40
ACTION_LINE = f"        uses: acme/l4-harness/.github/actions/l4@{SHA} # v0.4.62\n"
WORKFLOW = "jobs:\n  l4:\n    steps:\n      - id: l4\n{line}        with:\n          clis: none\n"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
OLDER = "0.4.60"


def sh(repo: Path, *args: str) -> str:
    done = subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True, text=True)
    return done.stdout


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        sh(root, "init", "-q", "-b", "main")
        self.environ = {"HOME": str(root / "home"), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}

    def write(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def commit_origin(self, files: dict[str, str]) -> None:
        """The base branch as last fetched: these files at `refs/remotes/origin/main`."""
        self.write(files)
        sh(self.root, "add", "-A")
        sh(self.root, "commit", "-q", "-m", "c")
        sh(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")

    def refs(self) -> str:
        return sh(self.root, "for-each-ref")

    def l4(self, *argv: str, environ: dict[str, str] | None = None) -> int:
        return main([*argv, "--repo", str(self.root)], environ={**self.environ, **(environ or {})})


def vendored(version: str) -> dict[str, str]:
    return {".l4/config.yaml": f"version: 1\nharness:\n  version: {version}\n"}


def action(line: str = ACTION_LINE) -> dict[str, str]:
    return {".l4/config.yaml": "version: 1\n", ".github/workflows/l4.yml": WORKFLOW.format(line=line)}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr("l4.cli_pin.__version__", OLDER)
    return Repo(tmp_path / "repo")


@pytest.fixture
def handled(monkeypatch):
    """FAKE_DISPATCH: every command handler is replaced by one that records the call, and prints one JSON document."""
    calls: list[str] = []

    def FAKE_DISPATCH(name, app, **options):  # noqa: N802
        calls.append(name)
        print(json.dumps({"command": name}))
        return CommandResult(ExitCode.OK)

    monkeypatch.setattr("l4.cli.dispatch", FAKE_DISPATCH)
    return calls


def pin_of(repo: Repo):
    from l4.cli import _build_app
    from l4.config.redaction import load_app_config  # noqa: F401 - the command line builds the same context

    app = _build_app(
        {"repo": repo.root, "config_path": None, "log_format": "human", "verbose": 0, "quiet": 0}, repo.environ
    )
    return cli_pin.pinned_version(app)


# --- the pin read ------------------------------------------------------------------------------------------------


def test_a_vendored_pin_is_read_at_the_base_as_last_fetched(repo):
    repo.commit_origin(vendored("0.4.62"))
    pin = pin_of(repo)
    assert (pin.version, pin.source) == ("0.4.62", "harness.version at origin/main")


def test_scn_ops_61_the_ref_wins_over_a_stale_tree_and_the_tree_is_read_without_a_ref(repo):
    repo.commit_origin(vendored("0.4.62"))
    repo.write(vendored("0.4.59"))
    assert pin_of(repo).version == "0.4.62"
    sh(repo.root, "update-ref", "-d", "refs/remotes/origin/main")
    pin = pin_of(repo)
    assert (pin.version, pin.source) == ("0.4.59", "harness.version in the working tree")


def test_a_v_prefix_is_accepted_and_anything_else_is_no_pin(repo):
    repo.write(vendored("v0.4.62"))
    assert pin_of(repo).version == "0.4.62"
    for bad in ("x", "0.4", '"main"', "0.4.62.1", "[1]"):
        repo.write(vendored(bad))
        assert pin_of(repo) is None, bad


def test_scn_ops_58_the_action_pin_is_the_comment_of_its_uses_line(repo):
    repo.write(action())
    pin = pin_of(repo)
    assert (pin.version, pin.repository) == ("0.4.62", "acme/l4-harness")
    assert pin.source == "the uses: line of .github/workflows/l4.yml in the working tree"
    for line in (
        f"        uses: acme/l4-harness/.github/actions/l4@{SHA} # main\n",
        f"        uses: acme/l4-harness/.github/actions/l4@{SHA}\n",
        "        uses: ./.github/actions/l4\n",
    ):
        repo.write(action(line))
        assert pin_of(repo) is None, line


def test_a_symlinked_or_oversized_configuration_is_no_pin(repo, tmp_path):
    (repo.root / ".l4").mkdir()
    target = tmp_path / "elsewhere.yaml"
    target.write_text("harness:\n  version: 0.4.62\n", encoding="utf-8")
    (repo.root / ".l4" / "config.yaml").symlink_to(target)
    assert pin_of(repo) is None
    (repo.root / ".l4" / "config.yaml").unlink()
    repo.write({".l4/config.yaml": "harness:\n  version: 0.4.62\n# " + "x" * (cli_pin.MAX_BYTES + 1)})
    assert pin_of(repo) is None
    # and the same two at the base branch
    sh(repo.root, "add", "-A")
    sh(repo.root, "commit", "-q", "-m", "big")
    sh(repo.root, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert pin_of(repo) is None


def test_a_directory_that_is_no_repository_is_no_pin(tmp_path, monkeypatch):
    monkeypatch.setattr("l4.cli_pin.__version__", OLDER)
    plain = Repo.__new__(Repo)
    plain.root, plain.environ = tmp_path, {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    assert pin_of(plain) is None


# --- the guard ---------------------------------------------------------------------------------------------------


def test_scn_ops_56_an_older_l4_is_refused_before_it_reads_anything(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.62"))
    refs = repo.refs()
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r") == 2
    err = capsys.readouterr().err
    assert (
        "retry: this l4 is 0.4.60, older than the harness this repository pins (0.4.62, harness.version at "
        "origin/main): it would apply the rules of 0.4.60 to the repository's units and plans"
    ) in err
    assert "Fix: install l4 v0.4.62, or pass --allow-older-cli to run this l4 anyway" in err
    assert handled == [] and repo.refs() == refs  # nothing ran, no ref was fetched or written


def test_the_fix_names_the_pinned_shim_when_the_repository_has_one(repo, handled, capsys):
    repo.commit_origin({**vendored("0.4.62"), ".l4/bin/l4": "#!/bin/sh\n"})
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r") == 2
    assert "Fix: use .l4/bin/l4 (it runs the pinned harness), or pass --allow-older-cli" in capsys.readouterr().err


def test_scn_ops_57_allow_older_cli_runs_it_with_a_warning(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.62"))
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r", "--allow-older-cli") == 0
    err = capsys.readouterr().err
    assert handled == ["retry"]
    assert "warning: this l4 is 0.4.60, older than the harness this repository pins (0.4.62, harness.version" in err
    assert "install l4 v0.4.62" in err


def test_scn_ops_58_an_action_pin_names_the_install_of_its_tag(repo, handled, capsys):
    repo.commit_origin(action())
    assert repo.l4("yolo", "activate", "p1", "--reason", "go") == 2
    err = capsys.readouterr().err
    assert "uv tool install --force git+https://github.com/acme/l4-harness@v0.4.62" in err
    assert handled == []
    for line in (
        f"        uses: acme/l4-harness/.github/actions/l4@{SHA} # main\n",
        f"        uses: acme/l4-harness/.github/actions/l4@{SHA}\n",
        "        uses: ./.github/actions/l4\n",
    ):
        repo.commit_origin(action(line))
        assert repo.l4("yolo", "activate", "p1", "--reason", "go") == 0, line
    assert handled == ["yolo activate"] * 3


def test_scn_ops_59_the_pinned_version_and_a_ci_job_say_nothing_and_a_newer_l4_only_warns(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.60"))
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r") == 0
    assert capsys.readouterr().err == ""
    repo.commit_origin(vendored("0.4.59"))  # the CLI is newer than the pin: a warning, never a refusal
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r") == 0
    err = capsys.readouterr().err
    assert "this l4 is 0.4.60, newer than the harness this repository pins (0.4.59" in err and "refus" not in err
    repo.commit_origin(vendored("0.4.62"))  # a CI job is untouched
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r", environ={"GITHUB_ACTIONS": "true"}) == 0
    assert capsys.readouterr().err == ""
    assert repo.l4("retry", "--unit", "openspec:a", "--reason", "r", environ={"GITLAB_CI": "true"}) == 0
    assert handled == ["retry"] * 4


def test_scn_ops_60_a_stop_and_a_local_write_only_warn_and_a_read_says_nothing(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.62"))
    warns = [
        ("yolo", "cancel", "p1", "--reason", "r"),
        ("yolo", "accept", "p1", "A", "--withdraw", "--reason", "r"),
        ("yolo", "waive", "p1", "F-1", "--withdraw", "--reason", "r"),
        ("feedback", "add", "--kind", "tests", "--text", "t"),
        ("questions", "accept", "Q-001", "--no-push"),
    ]
    for argv in warns:
        capsys.readouterr()
        assert repo.l4(*argv) == 0, argv
        assert "warning: this l4 is 0.4.60, older" in capsys.readouterr().err, argv
    for argv in (("status",), ("yolo", "status", "p1"), ("doctor",), ("upgrade", "--dry-run")):
        assert repo.l4(*argv) == 0, argv
        assert capsys.readouterr().err == "", argv
    assert len(handled) == len(warns) + 4


def test_scn_ops_61_the_base_as_last_fetched_wins_and_without_it_the_tree_is_read(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.62"))
    repo.write(vendored("0.4.59"))
    assert repo.l4("yolo", "resume", "p1", "--reason", "r") == 2
    assert "harness.version at origin/main" in capsys.readouterr().err
    sh(repo.root, "update-ref", "-d", "refs/remotes/origin/main")
    assert repo.l4("yolo", "resume", "p1", "--reason", "r") == 0  # the tree pins 0.4.59: the l4 is newer, a warning
    assert "newer" in capsys.readouterr().err and handled == ["yolo resume"]


def test_scn_ops_62_a_json_output_stays_one_document(repo, handled, capsys):
    repo.commit_origin(vendored("0.4.62"))
    assert repo.l4("yolo", "go", "p1", "--reason", "r", "--json", "--allow-older-cli") == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {"command": "yolo go"}  # exactly one document on stdout
    assert "warning: this l4 is 0.4.60, older" in err


# --- which commands -----------------------------------------------------------------------------------------------


def test_every_guarded_command_is_a_command_of_the_harness():
    assert set(cli_pin.WRITES) <= set(HANDLERS)


@pytest.mark.parametrize(
    ("name", "options", "kind"),
    [
        ("run", {}, "refuse"), ("run", {"dry_run": True}, None), ("verify", {}, "refuse"), ("archive", {}, "refuse"),
        ("resume", {}, "refuse"), ("retry", {}, "refuse"), ("restart", {}, "refuse"),
        ("plan", {"sweep": True}, "refuse"), ("plan", {}, None),
        ("questions", {"words": ("accept", "Q-001")}, "refuse"), ("questions", {"words": ("answer", "Q-1")}, "refuse"),
        ("questions", {"words": ("answer", "Q-1"), "no_push": True}, "warn"),
        ("questions", {"words": ("show", "Q")}, None), ("questions", {}, None),
        ("yolo review", {"local": True}, "refuse"), ("yolo review", {"worktree": True, "record": True}, "refuse"),
        ("yolo review", {"worktree": True}, None), ("yolo review", {}, None),
        ("yolo accept", {}, "refuse"), ("yolo accept", {"withdraw": True}, "warn"),
        ("yolo waive", {}, "refuse"), ("yolo waive", {"withdraw": True}, "warn"),
        ("yolo activate", {}, "refuse"), ("yolo resume", {}, "refuse"), ("yolo go", {}, "refuse"),
        ("yolo cancel", {}, "warn"), ("yolo draft", {}, "warn"), ("feedback add", {}, "warn"),
        ("feedback submit", {}, "warn"), ("feedback withdraw", {}, "warn"), ("feedback list", {}, None),
        ("lessons", {"words": ("promote", "L-1")}, "warn"), ("lessons", {"words": ("list",)}, None),
    ],
)  # fmt: skip
def test_the_table_of_commands(name, options, kind):
    rule = cli_pin.WRITES.get(name)
    assert (rule(options) if rule else None) == kind
