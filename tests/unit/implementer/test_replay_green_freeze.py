"""A replayed GREEN step meets the test-path freeze (restore_frozen + freeze_test_paths) like an agent step: the replay
guard is armed after the freeze, so its expected state must follow it. A frozen test path the saved patch changes stays
at its frozen version; it is not re-applied after the first gate and committed."""

import hashlib

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.discrimination import AtRed

from .conftest import IMPL, Bench, result
from .test_held_accept import answer_q, commit_all, patch_of, raise_held
from .test_tdd_green import CORRECTED, EXTRA_TEST, answer_naming, two_test_red
from .test_tdd_green import TASK as GREEN_TASK

WEAK_EXTRA = EXTRA_TEST.replace('assert apply_discount(10.0, "SAVE10") == 9.0', "assert True")


def forge_at_red(bench: Bench, raw, files: dict[str, str]) -> None:
    wb = bench.wb
    for rel, text in files.items():
        (wb.worktree / rel).write_text(text)
    wb.git.run("add", "-A", "-f", "--", *files)
    data = wb.git.run_bytes("diff", "--cached", "--binary", "HEAD")
    wb.git.run("reset", "-q")
    wb.discard_changes()
    patch_of(bench, "at_red").write_bytes(data)
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests", "result_sha256", "source_sha256", "saved")
    last = {k: v for k, v in bench.events("question.raised")[-1].items() if k in keep}
    bench.writer.append("question.raised", **{**last, "patch_sha256": hashlib.sha256(data).hexdigest()})
    commit_all(bench, raw, "forged at_red hold")


def test_a_replayed_green_step_keeps_a_frozen_test_the_freeze_put_back(make_bench, raw, monkeypatch):
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix, fix])
    red = tdd.run_red(bench.wb, GREEN_TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert "tests/test_extra.py" in red.manifest.files  # frozen by red; no answer unfreezes it
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")  # only test_discount.py is unfrozen
    reason = "the test-at-red run ran no test (exit 2, 0 collection errors)"
    monkeypatch.setattr(tdd, "fails_at_red", lambda *a, **k: AtRed([], reason))
    first = tdd.run_green(bench.wb, GREEN_TASK, red, attempt=1)
    assert first.status == "held" and first.held is not None and first.held.check == "at_red"
    qid = raise_held(bench, first.held)
    forge_at_red(bench, raw, {
        "tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL, "tests/test_extra.py": WEAK_EXTRA,
    })  # fmt: skip
    answer_q(bench, raw, qid, "accept: the run cannot be made here")
    second = tdd.run_green(bench.wb, GREEN_TASK, red, attempt=2)
    restored = bench.events("held.replay_restored")
    committed = bench.wb.git.run("show", "HEAD:tests/test_extra.py", check=False).stdout
    restored = bench.events("held.replay_restored")
    committed = bench.wb.git.run("show", "HEAD:tests/test_extra.py", check=False).stdout
    assert [e["check"] for e in bench.events("held.replayed")] == ["at_red"]
    assert second.status == "ok", second.reason
    assert committed != WEAK_EXTRA  # the frozen version stays: the replay guard does not re-apply the patch's
    assert committed == bench.wb.git.run("show", f"{red.manifest.red_sha}:tests/test_extra.py").stdout
    assert any(e.get("path") == "tests/test_extra.py" for e in bench.events("guard.test_tamper"))  # the freeze acted
    assert not any("tests/test_extra.py" in (e.get("paths") or []) for e in restored)  # the guard did not undo it

    from pathlib import Path

    from l4.state.ledger import read_ledger
    from l4.verifier.integrity import IntegrityContext, check_freeze

    wb = bench.wb
    events = read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events
    red_ok = [e for e in events if e.type == "task.red_ok"][-1]
    ctx = IntegrityContext(
        wb.git, wb.cfg, red_ok.data["base"], wb.head(), events, [(wb.ref.id, GREEN_TASK)], [wb.unit_rel], wb.ref.id
    )
    assert not any("frozen test or support file changed" in f.title and "tests/test_extra.py" in f.detail
                   for f in check_freeze(ctx).findings)  # fmt: skip
