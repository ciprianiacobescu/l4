"""An `accept` of a held check binds to the step the person looked at (L4-IMP-065, SCN-IMP-320..326): the held step's
changes are saved as a patch before they are discarded, an accept replays the patch instead of starting an agent, and a
patch that cannot be replayed is a new question, never a pass."""

import hashlib
import json
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.implementer import loop, tdd
from l4.implementer.discrimination import AtRed, Vacuity
from l4.implementer.loop import run_task
from l4.specs.questions import QuestionsFile, QuestionStatus, answer_sha256

from .conftest import IMPL, KNOWN, Bench, red_step, result
from .test_earlier_red import NEW, NEW_ID, OLD, TASK, commit_old, new_step
from .test_held_answers import answer
from .test_held_check import held_bench, no_test, zero_says
from .test_tdd_green import CORRECTED, answer_naming, two_test_red
from .test_tdd_green import TASK as GREEN_TASK

UNIT_REL = "openspec/changes/add-discount-codes"
RENAMED = NEW.replace("test_new_total", "test_total_renamed")
TOKEN = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"  # built from parts: this file holds no token shape


def renamed_step() -> Step:
    """What a later agent step would write: the same test under another name."""
    return Step(writes={"tests/test_new.py": RENAMED}, structured=result("red", criteria_ids=[KNOWN]))


def patch_of(bench: Bench, check: str = "pre_satisfied") -> Path:
    return bench.wb.ref.path / ".l4" / "held" / f"1.1-{check}.patch"


def tracked(bench: Bench, path: Path) -> bool:
    rel = path.relative_to(bench.wb.worktree).as_posix()
    return bench.wb.git.run("cat-file", "-e", f"HEAD:{rel}", check=False).returncode == 0


def held_new(make_bench, monkeypatch, script=None) -> Bench:
    """A red step that writes a passing test, held because the zero-value run cannot decide (Q-001 raised)."""
    zero_says(monkeypatch)
    bench = held_bench(make_bench, script or [new_step(), renamed_step()])
    first = run_task(bench.wb, TASK)
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"]), first.reason
    return bench


def commit_all(bench: Bench, raw, message: str = "edit") -> None:
    raw(bench.wb.worktree, "add", "-A")
    raw(bench.wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", message)


def question_text(bench: Bench) -> str:
    return (bench.wb.ref.path / "questions.md").read_text()


def test_scn_imp_320_a_hold_keeps_the_step_and_an_accept_replays_it_without_an_agent(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    patch = patch_of(bench)
    assert patch.is_file() and tracked(bench, patch)  # committed with the questions
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()
    assert b"test_new_total" in patch.read_bytes()
    [raised] = bench.events("question.raised")
    assert raised["patch_sha256"] == digest and raised["tests"] == [NEW_ID]
    assert bench.subjects()[-1].startswith("docs(") and bench.wb.is_clean()
    assert len(bench.adapter.requests) == 1
    answered = answer(bench, raw, "accept: the version pin cannot be shown to discriminate")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1  # no agent ran for the step: the answered test is the one that counts
    [replayed] = bench.events("held.replayed")
    assert (replayed["question"], replayed["task"], replayed["check"], replayed["patch_sha256"]) == (
        "Q-001", "1.1", "pre_satisfied", digest,
    )  # fmt: skip
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof["via"] == "human_override" and proof["question"] == "Q-001" and proof["answer_sha256"] == answered
    assert not patch.exists() and not tracked(bench, patch)  # deleted in the step's own commit
    assert (bench.wb.worktree / "tests" / "test_new.py").read_text() == NEW  # the test the person looked at
    assert bench.events("question.raised")[-1]["id"] == "Q-001"  # no second question


@pytest.mark.parametrize("damage", ["missing", "digest", "conflict"])
def test_scn_imp_321_a_patch_that_cannot_be_replayed_is_a_new_question_never_a_pass(
    make_bench, monkeypatch, raw, damage
):
    bench = held_new(make_bench, monkeypatch)
    patch = patch_of(bench)
    if damage == "missing":
        patch.unlink()
        sidecar = patch.with_suffix(".json")
        sidecar.unlink()
    elif damage == "digest":
        patch.write_bytes(patch.read_bytes() + b"\n")
    else:  # the branch moved: the file the patch creates exists now
        (bench.wb.worktree / "tests" / "test_new.py").write_text("# someone else\n")
    commit_all(bench, raw, "damage")
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and outcome.question_ids == ["Q-002"], outcome.reason
    assert len(bench.adapter.requests) == 1 and bench.events("check.accepted") == []
    assert bench.events("held.replayed") == [] and bench.events("task.done") == []
    why = {"missing": "missing", "digest": "digest", "conflict": "does not apply"}[damage]
    assert why in question_text(bench).split("## Q-002", 1)[1]
    assert "patch_sha256" not in bench.events("question.raised")[-1]  # nothing to replay for the new question
    file = QuestionsFile.load(bench.wb.ref.path / "questions.md")
    assert file.get("Q-002").blocking_tasks == ("1.1",)


def test_scn_imp_322_a_retry_deletes_the_patch_and_the_agent_runs_with_the_note(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    patch = patch_of(bench)
    answer(bench, raw, "retry: upgraded L4")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked", outcome.reason  # the agent's renamed test is held again, with its own patch
    assert len(bench.adapter.requests) == 2 and "upgraded L4" in bench.adapter.requests[-1].prompt
    assert any("held patch dropped" in s for s in bench.subjects())
    assert bench.events("held.replayed") == []
    assert b"test_total_renamed" in patch.read_bytes()  # the new hold wrote its own patch


def forge_hold(bench: Bench, raw, files: dict[str, str]) -> str:
    """Replace the saved patch by the patch of a step that wrote `files`, as a hold of that step would have saved it."""
    wb = bench.wb
    for rel, text in files.items():
        target = wb.worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    wb.git.run("add", "-A", "-f", "--", *files)
    data = wb.git.run_bytes("diff", "--cached", "--binary", "HEAD")
    wb.git.run("reset", "-q")
    wb.discard_changes()
    patch = patch_of(bench)
    patch.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests", "result_sha256")
    last = {k: v for k, v in bench.events("question.raised")[-1].items() if k in keep}
    bench.writer.append("question.raised", **{**last, "patch_sha256": digest})
    commit_all(bench, raw, "forged hold")
    return digest


def test_scn_imp_323_a_replayed_patch_that_writes_a_protected_path_has_it_put_back(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    forge_hold(bench, raw, {"tests/test_new.py": NEW, ".github/workflows/ci.yml": "on: push\n"})
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1 and bench.events("held.replayed")
    violations = [e for e in bench.events("guard.violation") if e["path"] == ".github/workflows/ci.yml"]
    assert violations and violations[0]["action"] == "removed"
    assert not (bench.wb.worktree / ".github/workflows/ci.yml").exists()


def test_scn_imp_323_a_replayed_patch_that_holds_a_secret_fails_the_step_as_an_agents_would(
    make_bench, monkeypatch, raw
):
    bench = held_new(make_bench, monkeypatch)
    forge_hold(bench, raw, {"tests/test_new.py": NEW + f'\nSECRET = "{TOKEN}"\n'})
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert len(bench.events("guard.secret")) == 1 and len(bench.events("task.attempt_failed")) == 1
    assert TOKEN not in (bench.wb.ref.path / "questions.md").read_text()
    # the replay is used once: the next attempt is an agent step
    assert len(bench.adapter.requests) == 2, outcome.reason
    assert len(bench.events("held.replayed")) == 1


def test_scn_imp_324_an_agent_write_to_the_held_path_is_put_back(make_bench):
    rel = f"{UNIT_REL}/.l4/held/1.1-pre_satisfied.patch"
    bench: Bench = make_bench([new_step((rel, "planted\n"))])
    held_dir = bench.wb.ref.path / ".l4" / "held"
    assert rel == f"{bench.wb.unit_rel}/.l4/held/1.1-pre_satisfied.patch"
    outcome = tdd.run_red(bench.wb, TASK, attempt=1)
    hits = [e for e in bench.events("guard.violation") if e["path"] == rel]
    assert hits and hits[0]["action"] == "removed", outcome.reason
    assert not (held_dir / "1.1-pre_satisfied.patch").exists()


def test_scn_imp_325_the_question_shows_the_redacted_source_of_each_test_cut_to_forty_lines(make_bench, monkeypatch):
    """An already-satisfied claim names a test that was committed earlier, so its text was never scanned for secrets."""
    body = f"    # key = {TOKEN}\n" + "".join(f"    assert total([1.0, 2.0]) == 3.0  # {n}\n" for n in range(60))
    long_old = OLD.replace("    assert total([1.0, 2.0]) == 3.0\n", body)
    zero_says(monkeypatch)
    bench: Bench = make_bench([no_test()])
    commit_old(bench, text=long_old)
    assert run_task(bench.wb, TASK).status == "blocked"
    text = question_text(bench).split("### Context", 1)[1].split("### Options", 1)[0]
    assert "def test_old_total" in text and TOKEN not in text and TOKEN[:12] not in text
    shown = [line for line in text.splitlines() if "assert total" in line]
    assert 0 < len(shown) <= 40
    assert "[cut: " in text and "more lines]" in text
    assert patch_of(bench).read_bytes() == b""  # nothing changed in the step: the patch is empty, the result is kept


def test_scn_imp_326_a_later_agent_step_is_told_which_tests_are_accepted(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine")
    calls = []

    def worse(wb, base, phase):
        calls.append(phase)
        return "lint got worse" if len(calls) == 1 else ""

    monkeypatch.setattr(tdd, "worse_static_gates", worse)
    outcome = run_task(bench.wb, TASK)
    # attempt 1 replayed the saved step and failed a gate; attempt 2 is an agent step, told which tests are accepted
    assert len(bench.events("held.replayed")) == 1 and len(bench.events("task.attempt_failed")) == 1
    assert len(bench.adapter.requests) == 2, outcome.reason
    prompt = bench.adapter.requests[-1].prompt
    assert 'source="accepted tests"' in prompt
    block = prompt.split('source="accepted tests"', 1)[1].split("</l4:data>", 1)[0]
    assert NEW_ID in block and "def test_new_total" in block and "unchanged" in block
    assert "same name" in block and "covers only them" in block


# --- the other held checks ----------------------------------------------------------------------------------------


def raise_held(bench: Bench, held_check) -> str:
    [qid] = loop._raise_held(bench.wb, GREEN_TASK, held_check, 1)
    return qid


def answer_q(bench: Bench, raw, qid: str, text: str) -> None:
    unit = bench.wb.ref.path
    file = QuestionsFile.load(unit / "questions.md")
    file = file.set_answer(qid, text).set_status(qid, QuestionStatus.ANSWERED)
    file.save(unit / "questions.md")
    commit_all(bench, raw, f"answer {qid}")
    digest = answer_sha256(QuestionsFile.load(unit / "questions.md").get(qid))
    bench.wb.emit("question.answered", id=qid, by="human", answer_sha256=digest)


def test_a_held_vacuity_check_is_replayed_after_an_accept(make_bench, monkeypatch, raw):
    monkeypatch.setattr(
        tdd,
        "vacuity_check",
        lambda wb, zeroed, open_criteria, *, real=None: Vacuity(inconclusive={c: "ran no test" for c in open_criteria}),
    )
    bench: Bench = make_bench([red_step(), red_step()])
    first = tdd.run_red(bench.wb, GREEN_TASK, attempt=1)
    assert first.status == "held" and first.held is not None and first.held.check == "vacuity"
    qid = raise_held(bench, first.held)
    assert patch_of(bench, "vacuity").is_file()
    answer_q(bench, raw, qid, "accept: run (b) cannot run here")
    second = tdd.run_red(bench.wb, GREEN_TASK, attempt=2)
    assert second.status == "ok", second.reason
    assert len(bench.adapter.requests) == 1
    [replayed] = bench.events("held.replayed")
    assert (replayed["check"], replayed["question"]) == ("vacuity", qid)
    assert not patch_of(bench, "vacuity").exists()


def test_a_held_test_at_red_check_is_replayed_after_an_accept(make_bench, raw, monkeypatch):
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix, fix])
    red = tdd.run_red(bench.wb, GREEN_TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    reason = "the test-at-red run ran no test (exit 2, 0 collection errors)"
    monkeypatch.setattr(tdd, "fails_at_red", lambda *a, **k: AtRed([], reason))
    first = tdd.run_green(bench.wb, GREEN_TASK, red, attempt=1)
    assert first.status == "held" and first.held is not None and first.held.check == "at_red"
    qid = raise_held(bench, first.held)
    assert patch_of(bench, "at_red").is_file()
    answer_q(bench, raw, qid, "accept: the run cannot be made here")
    requests = len(bench.adapter.requests)
    second = tdd.run_green(bench.wb, GREEN_TASK, red, attempt=2)
    assert second.status == "ok", second.reason
    assert len(bench.adapter.requests) == requests
    assert [e["check"] for e in bench.events("held.replayed")] == ["at_red"]
    assert not patch_of(bench, "at_red").exists()


def test_a_held_tests_chore_check_is_replayed_after_an_accept(make_bench, raw, monkeypatch):
    from l4.implementer.discrimination import ExtraRun

    from .test_criterion_tests_chore import BOUND, FINDINGS, run_bound
    from .test_single_phase import NEW_TESTS

    monkeypatch.setattr(
        tdd,
        "discriminate_extra",
        lambda wb, tests, base, **kw: ExtraRun(inconclusive=dict.fromkeys(tests, "did not run in test-extra-zero")),
    )
    step = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, first = run_bound(make_bench, step)
    assert first.status == "held" and first.held is not None and first.held.check == "tests"
    [qid] = loop._raise_held(bench.wb, BOUND, first.held, 1)
    held_patch = bench.wb.ref.path / ".l4" / "held" / "1.2-tests.patch"
    assert held_patch.is_file()
    answer_q(bench, raw, qid, "accept: the runs cannot decide")
    requests = len(bench.adapter.requests)
    second = tdd.run_single(bench.wb, BOUND, FINDINGS, attempt=2, kind="tests")
    assert second.status == "ok", second.reason
    assert len(bench.adapter.requests) == requests
    assert [e["check"] for e in bench.events("held.replayed")] == ["tests"]
    assert not held_patch.exists()
    assert json.loads(json.dumps(bench.events("task.tests_added")[-1]["tests"])) == [
        "tests.test_more::test_total_of_two"
    ]
