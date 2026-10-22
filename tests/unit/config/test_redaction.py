from l4.config.redaction import redactor_for_config
from l4.config.schema import L4Config

SECRET = "tok-secretvalue-9999"


def test_redactor_covers_redact_env_and_every_env_reference():
    cfg = L4Config.model_validate(
        {
            "forge": {"token_env": "MY_FORGE_TOK"},
            "observability": {"redact_env": ["EXTRA_SECRET"]},
            "profiles": {"p": {"adapter": "codex", "api_key_env": "MY_API_KEY"}},
        }
    )
    environ = {
        "MY_FORGE_TOK": SECRET + "-forge",
        "EXTRA_SECRET": SECRET + "-extra",
        "MY_API_KEY": SECRET + "-api",
        "UNRELATED": SECRET + "-other",
    }
    out = redactor_for_config(cfg, environ).redact_text(" ".join(environ.values()))
    assert out.count("[REDACTED:") == 3 and SECRET + "-other" in out


def test_non_secret_env_keys_are_not_redacted():
    cfg = L4Config.model_validate({"verifier": {"playwright": {"base_url_env": "MY_BASE_URL"}}})
    out = redactor_for_config(cfg, {"MY_BASE_URL": "http://localhost:3000/app"}).redact_text(
        "http://localhost:3000/app"
    )
    assert out == "http://localhost:3000/app"


def test_the_runners_job_token_is_redacted_by_default():
    environ = {"CI_JOB_TOKEN": "job-token-value-1234"}
    cfg = L4Config.model_validate({"version": 1})
    out = redactor_for_config(cfg, environ).redact_text("git said job-token-value-1234")
    assert "job-token-value" not in out


def test_the_job_token_inside_the_repository_url_is_redacted_when_the_variable_differs():
    environ = {
        "CI_JOB_TOKEN": "group-var-value",
        "CI_REPOSITORY_URL": "https://gitlab-ci-token:job-tok-real@forge.test/grp/proj.git",
    }
    cfg = L4Config.model_validate({"version": 1})
    out = redactor_for_config(cfg, environ).redact_text("git said job-tok-real and group-var-value")
    assert "job-tok-real" not in out and "group-var-value" not in out


def test_the_copilot_token_is_redacted_by_default():  # SCN-PRV-136
    from l4.config.defaults import DEFAULT_REDACT_ENV

    assert "COPILOT_GITHUB_TOKEN" in DEFAULT_REDACT_ENV
    plain = "copilot-fake-credential-0123456789"  # a value no token pattern would catch: the name does the work
    cfg = L4Config.model_validate({"version": 1})
    out = redactor_for_config(cfg, {"COPILOT_GITHUB_TOKEN": plain}).redact_text(f"copilot said {plain} and stopped")
    assert plain not in out and "0123456789" not in out and "[REDACTED:" in out
    placeholder = "github_pat_" + "x" * 40
    shaped = redactor_for_config(cfg, {"COPILOT_GITHUB_TOKEN": placeholder}).redact_text(f"token {placeholder} here")
    assert "xxxx" not in shaped and "github_pat_" not in shaped
