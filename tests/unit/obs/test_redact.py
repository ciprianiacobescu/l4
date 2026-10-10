import pytest

from l4.redact import TOKEN_SHAPES, Redactor

FAKE_SHAPES = {
    "anthropic-key": "sk-ant-api03-" + "A1b2C3d4" * 3,
    "openai-key": "sk-proj-" + "Z9y8X7w6" * 3,
    "github-token": "ghp_" + "a1B2c3D4e5" * 3,
    "github-pat": "github_pat_" + "Q1w2E3r4T5" * 3,
    "gitlab-pat": "glpat-" + "k9L8m7N6" * 3,
    "gitlab-trigger": "glptt-" + "k9L8m7N6" * 3,
    "gitlab-deploy": "gldt-" + "k9L8m7N6" * 3,
    "gitlab-job": "glcbt-" + "k9L8m7N6" * 3,
    "jwt": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJl",
    "mintkey": "mk_agent_" + "ABCD1234" * 3,
    "private-key": "-----BEGIN PRIVATE KEY-----\nMIIFAKE\nBODY\n-----END PRIVATE KEY-----",
}


def test_configured_values_and_shapes():
    secret = "hunter2-hunter2"
    redactor = Redactor({"L4_FORGE_TOKEN": secret, "SHORT": "abc", "EMPTY": ""})
    text = f"token={secret} short=abc end"
    out = redactor.redact_text(text)
    assert secret not in out
    assert "[REDACTED:L4_FORGE_TOKEN]" in out
    assert "short=abc" in out  # values under 8 characters are not redacted

    kinds = {kind for kind, _ in TOKEN_SHAPES}
    assert kinds >= set(FAKE_SHAPES)
    for kind, fake in FAKE_SHAPES.items():
        redacted = Redactor({}).redact_text(f"before {fake} after")
        assert fake not in redacted, kind
        assert f"[REDACTED:{kind}]" in redacted
        assert redacted.startswith("before ") and redacted.endswith(" after")


def test_longer_values_are_replaced_first():
    redactor = Redactor({"A": "supersecret", "B": "supersecret-extended"})
    out = redactor.redact_text("x supersecret-extended y")
    assert "extended" not in out


def test_benign_text_is_untouched():
    text = "pip install scikit-learn; sk-learn is not a key; ghp is short"
    assert Redactor({}).redact_text(text) == text


@pytest.mark.parametrize("obj", [{"a": ["xx hunter2-hunter2 yy", 3, None], "k": {"n": "hunter2-hunter2"}}])
def test_redact_obj_walks_containers(obj):
    out = Redactor({"T": "hunter2-hunter2"}).redact_obj(obj)
    assert "hunter2" not in repr(out)
    assert out["a"][1] == 3 and out["a"][2] is None


def test_from_env_reads_only_named_variables():
    env = {"L4_FORGE_TOKEN": "forge-token-value", "OTHER": "other-value-123"}
    redactor = Redactor.from_env(["L4_FORGE_TOKEN", "MISSING"], env)
    assert "forge-token-value" not in redactor.redact_text("forge-token-value")
    assert "other-value-123" in redactor.redact_text("other-value-123")


@pytest.mark.parametrize(
    "ident",
    [
        "add-task-assignment-endpoint", "risk-scoring-pipeline-v2",
        "desk-booking-calendar-view", "kiosk-checkout-flow-v3",
    ],  # fmt: skip
)
def test_prefix_inside_an_identifier_is_not_a_token(ident):
    text = f"l4/openspec/{ident} openspec:{ident}"
    assert Redactor({}).redact_text(text) == text


def test_real_shapes_still_redacted_after_a_delimiter():
    for fake in ("key=sk-" + "a" * 40, "(sk-proj-" + "A1" * 20 + ")", '"ghp_' + "a1B2c3D4e5" * 3 + '"'):
        assert "[REDACTED:" in Redactor({}).redact_text(fake)
    assert "sk-" not in Redactor({}).redact_text("key=sk-" + "a" * 40)


def test_adopt_widens_in_place():
    redactor = Redactor({"A": "first-secret-1"})
    redactor.adopt(Redactor({"B": "second-secret-2"}))
    out = redactor.redact_text("first-secret-1 second-secret-2")
    assert out == "[REDACTED:A] [REDACTED:B]"
