"""`l4 setup github` (github-parity 4.1, L4-GHP-011) against a fake of the GitHub API."""

import base64

import pytest
from nacl import public

from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor

from .fake_github import REPO, TOKEN, FakeGitHub

SECRET_VALUE = "sk-ant-oat01-thesecretvalue"


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def project(tmp_path, raw):
    repo = tmp_path / "adopter"
    repo.mkdir()
    raw(repo, "init", "-q")
    raw(repo, "remote", "add", "origin", f"https://github.com/{REPO}.git")
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("ci:\n  runner_tags: []\n", encoding="utf-8")
    return repo


@pytest.fixture
def run_setup(project, git_environ, github, capsys):
    from l4.setup.github import run_setup_github

    def run(*, env: dict | None = None, gh: FakeGitHub | None = None, **options) -> tuple[int, str]:
        gh = gh or github
        environ = {**git_environ, "GH_TOKEN": TOKEN, "CLAUDE_CODE_OAUTH_TOKEN": SECRET_VALUE, **(env or {})}
        app = AppContext(
            repo=project, config_path=None, log_format="human", verbosity=0, run_id="r-20261011T1000Z-0001",
            environ=environ, redactor=Redactor({}),
        )  # fmt: skip
        options.setdefault("transport", gh.transport())
        try:
            code = run_setup_github(app, **options)
        except L4Exit as exc:
            out = capsys.readouterr()
            return int(exc.code), out.out + out.err + str(exc)
        out = capsys.readouterr()
        return int(code), out.out + out.err

    return run


SECRET = ("CLAUDE_CODE_OAUTH_TOKEN=CLAUDE_CODE_OAUTH_TOKEN",)


def rows(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.split(" ", 1)[0] in ("KEPT", "SET", "CREATED", "FAILED")]


def test_bare_repository_is_set_up_in_one_command(run_setup, github):
    """SCN-GHP-17: every row is CREATED or SET, and the workflow is dispatched on the base branch."""
    code, out = run_setup(secret=SECRET)
    assert code == 0, out
    found = rows(out)
    assert found and all(r.startswith(("CREATED", "SET")) for r in found), out
    assert github.workflow_permissions == {
        "default_workflow_permissions": "write",
        "can_approve_pull_request_reviews": True,
    }
    assert github.environments["l4"]["deployment_branch_policy"] == {
        "protected_branches": False,
        "custom_branch_policies": True,
    }
    assert [p["name"] for p in github.policies["l4"]] == ["main", "l4/*", "l4/**/*"]
    assert all(p["type"] == "branch" for p in github.policies["l4"])
    assert ("l4", "CLAUDE_CODE_OAUTH_TOKEN") in github.secrets
    assert github.variables == {"L4_SELF_PROVISION": "true"}
    assert {"l4:intake", "l4:in_review", "l4:needs-answers", "l4:resume"} <= set(github.labels)
    assert ("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches") in github.requests
    assert not github.strays


def test_second_run_keeps_everything(run_setup, github):
    """SCN-GHP-18: no --secret, every row KEPT, and nothing is written (the dispatch is not a state row)."""
    run_setup(secret=SECRET)
    before = len(github.requests)
    code, out = run_setup(dry_run=True)
    assert code == 0, out
    assert rows(out) and all(r.startswith("KEPT") for r in rows(out)), out
    code, out = run_setup()
    assert code == 0, out
    assert all(r.startswith("KEPT") for r in rows(out)), out
    again = github.requests[before:]
    writes = [r for r in again if r[0] != "GET"]
    assert writes == [("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches")]


def test_dry_run_sends_only_reads(run_setup, github):
    code, out = run_setup(secret=SECRET, dry_run=True)
    assert code == 0, out
    assert github.writes() == []
    assert any(r.startswith(("CREATED", "SET")) for r in rows(out)), out
    assert "dry-run" in out


def test_sealed_secret_decrypts_with_the_environments_key(run_setup, github):
    run_setup(secret=SECRET)
    sent = github.secrets[("l4", "CLAUDE_CODE_OAUTH_TOKEN")]
    assert sent["key_id"] == "kid-1"
    opened = public.SealedBox(github.key).decrypt(base64.b64decode(sent["encrypted_value"]))
    assert opened.decode() == SECRET_VALUE


def test_a_given_secret_is_set_again_never_kept(run_setup, github):
    run_setup(secret=SECRET)
    _, out = run_setup(secret=SECRET)
    assert any(r.startswith("SET") and "CLAUDE_CODE_OAUTH_TOKEN" in r for r in rows(out)), out


def test_missing_secret_source_is_a_failed_row_naming_the_variable(run_setup, github):
    code, out = run_setup(secret=("X_KEY=NOT_IN_THE_ENVIRONMENT",))
    assert code == int(ExitCode.DOCTOR_FAILED)
    assert any(r.startswith("FAILED") and "NOT_IN_THE_ENVIRONMENT" in r for r in rows(out)), out
    assert ("l4", "X_KEY") not in github.secrets


def test_non_admin_token_is_refused_before_any_write(run_setup, github):
    github.admin = False
    code, out = run_setup(secret=SECRET)
    assert code != 0
    assert "admin" in out
    assert github.writes() == []


def test_no_output_holds_the_token_or_a_secret_value(run_setup, github, capsys):
    github.admin = False
    _, refused = run_setup(secret=SECRET)
    github.admin = True
    _, done = run_setup(secret=SECRET)
    _, dry = run_setup(secret=SECRET, dry_run=True)
    for text in (refused, done, dry):
        assert TOKEN not in text and SECRET_VALUE not in text


def test_token_never_in_an_error_message(run_setup, github):
    bad = FakeGitHub(token="other-token")  # the server wants another token: every call is 401
    code, out = run_setup(gh=bad)
    assert code != 0 and TOKEN not in out


def test_runner_tags_set_means_no_self_provision_variable(run_setup, github, project):
    (project / ".l4" / "config.yaml").write_text("ci:\n  runner_tags: [agentic]\n", encoding="utf-8")
    run_setup()
    assert github.variables == {}


def test_a_different_variable_is_patched(run_setup, github):
    github.variables["L4_SELF_PROVISION"] = "false"
    _, out = run_setup()
    assert github.variables["L4_SELF_PROVISION"] == "true"
    assert any(r.startswith("SET") and "L4_SELF_PROVISION" in r for r in rows(out)), out


def test_repo_option_and_api_base_with_a_path_prefix(run_setup):
    """The live run goes through a broker that adds a path prefix and whose `Link` headers name api.github.com."""
    broker = FakeGitHub(base="http://localhost:8000/v1/call/svc_1")
    code, out = run_setup(gh=broker, api_url=broker.base, repo=REPO)
    assert code == 0, out
    assert broker.writes() and not broker.strays
    assert broker.labels  # created through the prefixed base


def test_plain_http_is_only_for_loopback(run_setup, github):
    code, out = run_setup(api_url="http://example.com/api")
    assert code == int(ExitCode.USAGE_ERROR) and "https" in out


def test_repo_defaults_to_the_origin(run_setup, github):
    code, _ = run_setup(dry_run=True)
    assert code == 0
    assert ("GET", f"/repos/{REPO}") in github.requests
