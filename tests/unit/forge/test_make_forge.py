import httpx
import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import ForgeUnavailable, fetch_auth_config, make_forge, require_forge_target, require_token_in_ci

from .conftest import TOKEN


def cfg(**forge: object) -> L4Config:
    return L4Config.model_validate({"forge": forge})


def seen_url(forge) -> str:
    urls: list[str] = []
    forge._transport = httpx.MockTransport(lambda r: urls.append(str(r.url)) or httpx.Response(200, json=[]))
    forge.find_pr("b")
    return urls[0]


def test_no_token_is_unavailable_not_an_error():
    with pytest.raises(ForgeUnavailable, match="L4_FORGE_TOKEN is not set"):
        make_forge(cfg(), {})


def test_inside_ci_the_ci_variables_win():
    env = {
        "L4_FORGE_TOKEN": TOKEN, "GITLAB_CI": "true",
        "CI_API_V4_URL": "https://ci.example.test/api/v4", "CI_PROJECT_ID": "118",
    }  # fmt: skip
    config = cfg(gitlab={"api_url": "https://cfg.example.test/api/v4", "project": "g/p"})
    assert seen_url(make_forge(config, env)).startswith("https://ci.example.test/api/v4/projects/118/")


def test_outside_ci_the_config_is_used_and_ci_variables_are_ignored():
    env = {"L4_FORGE_TOKEN": TOKEN, "CI_API_V4_URL": "https://stale.example.test/api/v4", "CI_PROJECT_ID": "1"}
    config = cfg(gitlab={"api_url": "https://cfg.example.test/api/v4", "project": "g/p"})
    assert seen_url(make_forge(config, env)).startswith("https://cfg.example.test/api/v4/projects/g%2Fp/")


def test_a_token_without_a_place_to_send_it_is_a_config_error():
    with pytest.raises(L4Exit) as err:
        make_forge(cfg(), {"L4_FORGE_TOKEN": TOKEN})
    assert err.value.code == ExitCode.USAGE_ERROR and TOKEN not in str(err.value)


def test_an_unsafe_api_url_is_a_config_error():
    config = cfg(gitlab={"api_url": "http://gitlab.example.test/api/v4", "project": "1"})
    with pytest.raises(L4Exit) as err:
        make_forge(config, {"L4_FORGE_TOKEN": TOKEN})
    assert err.value.code == ExitCode.USAGE_ERROR


def test_the_token_variable_name_is_configurable():
    config = cfg(token_env="MY_TOK", gitlab={"api_url": "https://g.example.test/api/v4", "project": "1"})
    make_forge(config, {"MY_TOK": TOKEN})
    with pytest.raises(ForgeUnavailable):
        make_forge(config, {"L4_FORGE_TOKEN": TOKEN})


def test_a_token_env_name_that_is_not_a_name_fails_the_config():
    with pytest.raises(ValueError):
        cfg(token_env="X; rm -rf /")


def test_ci_without_the_token_is_exit_3_and_names_the_variable():
    with pytest.raises(L4Exit) as err:
        require_token_in_ci(cfg(), {"GITLAB_CI": "true"})
    assert err.value.code == ExitCode.DOCTOR_FAILED and "L4_FORGE_TOKEN" in str(err.value)
    require_token_in_ci(cfg(), {})  # outside CI the hooks skip instead
    require_token_in_ci(cfg(), {"GITLAB_CI": "true", "L4_FORGE_TOKEN": TOKEN})
    require_token_in_ci(cfg(type="local"), {"GITLAB_CI": "true"})


def _preflight_app(tmp_path, git_environ, origin: str | None, **env: str):
    import subprocess

    from l4.context import AppContext
    from l4.redact import Redactor

    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=git_environ)
    if origin:
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", origin], check=True, env=git_environ)
    environ = {**git_environ, "L4_FORGE_TOKEN": TOKEN, "L4_CACHE": str(tmp_path.parent / "cache"), **env}
    return AppContext(tmp_path, None, "human", 0, "r-1", environ, Redactor({}))


def _runnable_cfg():
    """A config whose only gap is the one a test is about (the preflight checks the roles too)."""
    return L4Config.model_validate({
        "profiles": {"a": {"adapter": "codex", "model": "m", "auth": "subscription", "vendor": "openai"}},
        "roles": {"implementer": ["a"], "judges": ["a"]},
    })  # fmt: skip


def test_a_token_without_url_or_project_outside_ci_is_exit_2_in_preflight(tmp_path, git_environ):
    from l4.config.preflight import preflight_run_config

    app = _preflight_app(tmp_path / "r", git_environ, None)  # no origin either
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app, _runnable_cfg())
    assert err.value.code == ExitCode.USAGE_ERROR and "forge.gitlab.api_url" in str(err.value)


def test_a_laptop_clone_needs_no_project_setting_in_preflight(tmp_path, git_environ):
    """SCN-OPS-18 (L4-OPS-011): a github.com origin and a token, no GITHUB_REPOSITORY: no exit 2."""
    from l4.config.preflight import preflight_run_config

    app = _preflight_app(tmp_path / "gh", git_environ, "git@github.com:o/n.git")
    preflight_run_config(app, _runnable_cfg())
    gitlab = _preflight_app(tmp_path / "gl", git_environ, "git@gitlab.example.com:g/sub/p.git")
    preflight_run_config(gitlab, _runnable_cfg())


def test_require_forge_target_is_quiet_without_a_token_or_with_a_complete_target():
    require_forge_target(cfg(), {})  # the forge hooks skip
    require_forge_target(cfg(type="local"), {"L4_FORGE_TOKEN": TOKEN})
    require_forge_target(cfg(gitlab={"api_url": "https://x.test/api/v4", "project": "g/p"}), {"L4_FORGE_TOKEN": TOKEN})


def test_fetch_auth_config_only_exists_with_a_token_and_never_holds_its_value():
    assert fetch_auth_config(cfg(), {}) == () and fetch_auth_config(cfg(type="local"), {"L4_FORGE_TOKEN": TOKEN}) == ()
    pairs = fetch_auth_config(cfg(), {"L4_FORGE_TOKEN": TOKEN})
    assert pairs and TOKEN not in repr(pairs) and "$L4_FORGE_TOKEN" in repr(pairs)
