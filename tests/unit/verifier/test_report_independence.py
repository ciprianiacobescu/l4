from l4.config.schema import L4Config
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.selection import assess_independence

from .test_report import result

CFG = L4Config.model_validate(
    {
        "profiles": {
            "codex": {"adapter": "codex", "vendor": "openai"},
            "claude": {"adapter": "claude-code", "vendor": "anthropic"},
            "free": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "zhipu"},
        }
    }
)


def test_declared_vendor_marks_independence_unverified():
    record = assess_independence(CFG, ["codex"], "free")
    out = result(independence=record)
    text = render_verification_md(out)
    assert "- independence: declared (unverified): free zhipu (declared), codex openai (tool)" in text
    assert verdict_json(out)["independence"]["status"] == "declared (unverified)"
    assert verdict_json(out)["independence"]["verified"] is False


def test_a_served_judge_against_a_tool_implementer_is_verified():
    record = assess_independence(CFG, ["codex"], "claude", served_model="claude-haiku-4-5-20251001")
    out = result(independence=record)
    assert (
        "- independence: verified (different_vendor): claude anthropic (served claude-haiku-4-5-20251001), "
        "codex openai (tool)" in render_verification_md(out)
    )
    judge = verdict_json(out)["independence"]["judge"]
    assert judge["provenance"] == "served" and judge["served"] == "claude-haiku-4-5-20251001"


def test_no_record_no_line():
    out = result()
    assert "independence" not in render_verification_md(out)
    assert verdict_json(out)["independence"] is None
