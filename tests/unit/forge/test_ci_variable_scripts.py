"""HB-2: the two scripts that store harness secrets as GitLab CI/CD variables scope them to an environment (default
`l4`), so the project's own jobs, which run in no environment, never receive them. Fakes only: no GitLab, no Mintkey."""

import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "forge"
SECRET = "glpat-" + "S3cr3tV4lue0123456789"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGitLab:
    """The slice of the project API the scripts use; `variables` are kept the way GitLab keeps them (key + scope)."""

    def __init__(self, variables=()) -> None:
        self.variables = [dict(v) for v in variables]
        self.calls: list[tuple[str, str, dict | None]] = []

    def handle(self, method: str, path: str, body: dict | None):
        self.calls.append((method, path, body))
        route, _, query = path.partition("?")
        parts = route.split("/")
        if route.endswith("/access_tokens"):
            if method == "GET":
                return []
            return {"id": 7, "name": body["name"], "scopes": body["scopes"], "access_level": 30, "user_id": 9,
                    "expires_at": body["expires_at"], "token": SECRET}  # fmt: skip
        if parts[-1] == "variables" or parts[-2:-1] == ["variables"]:
            if method == "GET" and parts[-1] == "variables":
                return [dict(v) for v in self.variables]
            if method == "POST":
                self.variables.append({"environment_scope": "*", **body})
                return {}
            if method == "PUT":
                scope = urllib.parse.parse_qs(query).get("filter[environment_scope]", ["*"])[0]
                hit = next(v for v in self.variables if v["key"] == parts[-1] and v["environment_scope"] == scope)
                hit.update(body)
                return {}
        if len(parts) == 2 and parts[0] == "projects":
            return {"path_with_namespace": "g/p"}
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def bot(monkeypatch, capsys):
    module = load("gitlab_bot_token")
    gitlab = FakeGitLab()

    class Api:
        def __init__(self, base, header):
            self.base, self.header = base, header

        def call(self, method, path, body=None):
            return gitlab.handle(method, path, body)

    monkeypatch.setattr(module, "Api", Api)
    monkeypatch.setenv("ADMIN_TOKEN", "admin-credential")

    def run(*extra: str) -> str:
        argv = ["--api-base", "https://gl/api/v4", "--auth-env", "ADMIN_TOKEN", "--project", "118", *extra]
        monkeypatch.setattr("sys.argv", ["gitlab_bot_token.py", *argv])
        assert module.main() == 0
        return capsys.readouterr().out

    run.gitlab = gitlab
    return run


def stored(gitlab: FakeGitLab, key="L4_FORGE_TOKEN"):
    rows = [v for v in gitlab.variables if v["key"] == key]
    return [(v["key"], v["environment_scope"], v["masked"], v["protected"]) for v in rows]


def test_the_bot_token_variable_is_created_scoped_to_the_l4_environment_by_default(bot):
    out = bot()
    assert stored(bot.gitlab) == [("L4_FORGE_TOKEN", "l4", True, False)]
    post = next(c for c in bot.gitlab.calls if c[0] == "POST" and c[1].endswith("/variables"))
    assert post[2]["environment_scope"] == "l4" and post[2]["masked"] is True
    assert "environment scope l4" in out and SECRET not in out  # the value is never printed


def test_an_explicit_scope_is_used(bot):
    bot("--environment-scope", "harness")
    assert stored(bot.gitlab)[0][1] == "harness"
    other = bot.gitlab.variables[0]
    assert other["environment_scope"] == "harness"


def test_an_existing_scoped_variable_is_updated_in_that_scope_only(bot):
    bot.gitlab.variables = [
        {"key": "L4_FORGE_TOKEN", "environment_scope": "*", "masked": True, "protected": False, "value": "old-star"},
        {"key": "L4_FORGE_TOKEN", "environment_scope": "l4", "masked": True, "protected": False, "value": "old-l4"},
    ]
    bot("--rotate")
    put = next(c for c in bot.gitlab.calls if c[0] == "PUT")
    assert put[1].endswith("/variables/L4_FORGE_TOKEN?filter[environment_scope]=l4")
    values = {v["environment_scope"]: v["value"] for v in bot.gitlab.variables}
    assert values == {"*": "old-star", "l4": SECRET}  # the unscoped one is not touched


def test_a_leftover_unscoped_variable_is_reported_never_deleted(bot):
    bot.gitlab.variables = [
        {"key": "L4_FORGE_TOKEN", "environment_scope": "*", "masked": True, "protected": False, "value": "old-star"}
    ]
    out = bot()
    assert "WARN" in out and "unscoped" in out and "delete" in out and "old-star" not in out
    assert not [c for c in bot.gitlab.calls if c[0] == "DELETE"]
    assert {v["environment_scope"] for v in bot.gitlab.variables} == {"*", "l4"}


def test_the_kept_branch_checks_presence_in_the_requested_scope(bot):
    bot.gitlab.variables = [
        {"key": "L4_FORGE_TOKEN", "environment_scope": "l4", "masked": True, "protected": False, "value": "v"}
    ]
    bot.gitlab.handle = lambda m, p, b, real=bot.gitlab.handle: (
        [{"name": "l4-bot", "active": True, "revoked": False, "id": 3, "scopes": ["api"], "access_level": 30,
          "expires_at": "2027-01-01"}] if p.endswith("/access_tokens") else real(m, p, b)
    )  # fmt: skip
    out = bot()
    assert "(kept)" in out and "environment scope l4" in out
    assert not [c for c in bot.gitlab.calls if c[0] in ("POST", "PUT")]


@pytest.fixture
def mintkey(monkeypatch, capsys):
    module = load("gitlab_ci_var_from_mintkey")
    gitlab = FakeGitLab()
    monkeypatch.setattr(module, "_agent_key", lambda: "mk_agent_fake")
    monkeypatch.setattr(module, "secret_value", lambda name: SECRET)

    def fake_json(req):
        url = req.full_url
        if url.endswith("/v1/tools/list_services"):
            return {"services": [{"id": "svc_1", "slug": "example-gitlab"}]}
        if url.endswith("/v1/tools/request_token"):
            return {"token": "jwt"}
        path = url.split("/svc_1/", 1)[1]
        body = json.loads(req.data) if req.data else None
        if req.get_method() == "GET" and path.count("/variables/") == 1:  # the read-back of one variable
            key = path.split("/variables/")[1].split("?")[0]
            scope = urllib.parse.parse_qs(path.partition("?")[2]).get("filter[environment_scope]", ["*"])[0]
            return next(v for v in gitlab.variables if v["key"] == key and v["environment_scope"] == scope)
        return gitlab.handle(req.get_method(), path, body)

    monkeypatch.setattr(module, "_json", fake_json)

    def run(*extra: str) -> str:
        argv = ["x.py", "--secret", "typesafe-jev-api-key", "--project", "118"]
        argv += ["--variable", "TYPESAFE_API_KEY", *extra]
        monkeypatch.setattr("sys.argv", argv)
        assert module.main() == 0
        return capsys.readouterr().out

    run.gitlab = gitlab
    return run


def test_the_mintkey_copy_is_scoped_to_the_l4_environment_by_default(mintkey):
    out = mintkey()
    assert stored(mintkey.gitlab, "TYPESAFE_API_KEY") == [("TYPESAFE_API_KEY", "l4", True, False)]
    assert "environment scope l4" in out and SECRET not in out


def test_the_mintkey_copy_updates_in_scope_and_warns_about_an_unscoped_leftover(mintkey):
    mintkey.gitlab.variables = [
        {"key": "TYPESAFE_API_KEY", "environment_scope": "*", "masked": True, "protected": False, "value": "old-star"},
        {"key": "TYPESAFE_API_KEY", "environment_scope": "l4", "masked": True, "protected": False, "value": "old-l4"},
    ]
    out = mintkey("--environment-scope", "l4")
    put = next(c for c in mintkey.gitlab.calls if c[0] == "PUT")
    assert put[1].endswith("/variables/TYPESAFE_API_KEY?filter[environment_scope]=l4")
    assert {v["environment_scope"]: v["value"] for v in mintkey.gitlab.variables} == {"*": "old-star", "l4": SECRET}
    assert "WARN" in out and "unscoped" in out and "old-star" not in out
