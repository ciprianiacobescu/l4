"""An `accept` of a held check binds to the step the person looked at (L4-IMP-065, SCN-IMP-320..326): the held step's
changes are saved as a patch before they are discarded, an accept replays the patch instead of starting an agent, and a
patch that cannot be replayed is a new question, never a pass."""

import hashlib
import json
import sys
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
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests", "result_sha256", "source_sha256")
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


def test_scn_imp_326_a_later_agent_step_is_told_the_earlier_accept_covers_nothing_now(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine")
    calls = []

    def worse(wb, base, phase):
        calls.append(phase)
        return "lint got worse" if len(calls) == 1 else ""

    monkeypatch.setattr(tdd, "worse_static_gates", worse)
    outcome = run_task(bench.wb, TASK)
    # attempt 1 replayed the saved step and failed a gate; attempt 2 is an agent step, told the accept is used up
    assert len(bench.events("held.replayed")) == 1 and len(bench.events("task.attempt_failed")) == 1
    assert len(bench.adapter.requests) == 2, outcome.reason
    prompt = bench.adapter.requests[-1].prompt
    assert 'source="accepted tests"' in prompt
    block = prompt.split('source="accepted tests"', 1)[1].split("</l4:data>", 1)[0]
    assert "earlier step" in block and "covers nothing" in block and "new answer" in block
    assert "def test_new_total" not in block  # no source, no claim of coverage
    # the agent's second attempt wrote another test: the used-up accept covers nothing, a new question is raised
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"])


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


# --- review round: the accept binds to the content, the question shows every change, the replay is an agent step ----

WEAK = NEW.replace("assert total([2.0, 2.0]) == 4.0", "assert True  # not the body the person was shown")
CONFTEST = (
    "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _support(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"
)


def weak_step() -> Step:
    """A later agent step: the SAME test id as the accepted one, another body."""
    return Step(writes={"tests/test_new.py": WEAK}, structured=result("red", criteria_ids=[KNOWN]))


def fail_lint_once(monkeypatch) -> None:
    calls: list[str] = []

    def worse(wb, base, phase):
        calls.append(phase)
        return "lint got worse" if len(calls) == 1 else ""

    monkeypatch.setattr(tdd, "worse_static_gates", worse)


def old_style(bench: Bench) -> None:
    """Record Q-001 again as 0.4.16 did: no saved step, no digests."""
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests")
    bench.writer.append(
        "question.raised", **{k: v for k, v in bench.events("question.raised")[-1].items() if k in keep}
    )


def test_m1_a_same_id_other_body_is_not_covered_after_the_replay_failed_a_gate(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [new_step(), weak_step()])
    assert "source_sha256" in bench.events("question.raised")[-1]
    answer(bench, raw, "accept: the version pin cannot be shown to discriminate")
    fail_lint_once(monkeypatch)
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason
    assert len(bench.events("held.replayed")) == 1 and bench.events("task.done") == []
    assert "assert True" in question_text(bench).split("## Q-002", 1)[1]  # the new body is what the new question shows


def test_m1_a_reopened_task_does_not_carry_the_old_accept_to_another_body(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [new_step(), weak_step()])
    bench.wb.emit("tasks.reopened", tasks=["1.1"])
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason
    assert bench.events("held.replayed") == [] and bench.events("check.accepted") == []


def test_m1_a_question_without_digests_keeps_the_id_only_rule(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [new_step(), weak_step()])
    old_style(bench)
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason  # as on 0.4.16: the id is what the answer covers


def test_m2_the_question_lists_every_changed_path_and_shows_the_diff_of_a_support_file(make_bench, monkeypatch):
    bench = held_new(make_bench, monkeypatch, [new_step(("tests/conftest.py", CONFTEST))])
    text = question_text(bench).split("### Context", 1)[1].split("### Options", 1)[0]
    assert "tests/conftest.py" in text and "tests/test_new.py" in text and "(2 files)" in text
    assert "_support" in text and "autouse=True" in text  # the diff of the non-test file
    assert "replays exactly the saved change of 2 files" in text and ".l4/held/1.1-pre_satisfied.patch" in text


def test_m2_an_at_red_question_shows_the_production_diff_and_cuts_a_long_one(make_bench, raw, monkeypatch):
    long_impl = IMPL + "".join(f"\n\ndef extra_{n}():\n    return {n}\n" for n in range(40))
    fix = Step(
        writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": long_impl}, structured=result("green")
    )
    bench = make_bench([two_test_red(), fix])
    red = tdd.run_red(bench.wb, GREEN_TASK, attempt=1)
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    monkeypatch.setattr(tdd, "fails_at_red", lambda *a, **k: AtRed([], "the test-at-red run ran no test"))
    first = tdd.run_green(bench.wb, GREEN_TASK, red, attempt=1)
    qid = raise_held(bench, first.held)
    text = question_text(bench).split(f"## {qid}", 1)[1]
    assert "src/pytdd/pricing.py" in text and "CODES" in text and "[cut: " in text
    assert "replayed too" in text and "1.1-at_red.patch" in text


def test_m3_the_replay_resets_the_setup_so_the_gate_sees_the_replayed_environment(
    make_bench, tdd_repo, monkeypatch, raw, tmp_path
):
    install = tmp_path / "install.py"
    install.write_text(
        "import os\nos.makedirs('.venv', exist_ok=True)\n"
        "data = open('uv.lock').read() if os.path.exists('uv.lock') else ''\n"
        "open('.venv/installed.txt', 'w').write(data)\n"
    )
    pin_test = (
        "from pathlib import Path\n\nimport pytest\n\n\n"
        f'@pytest.mark.l4("{KNOWN}")\ndef test_pin():\n'
        "    assert Path('.venv/installed.txt').read_text() == 'fastlib==2\\n'\n"
    )
    step = Step(writes={"uv.lock": "fastlib==2\n", "tests/test_pin.py": pin_test},
                structured=result("red", criteria_ids=[KNOWN]))  # fmt: skip
    zero_says(monkeypatch)
    bench = make_bench([step], setup=[tdd_repo.setup_command, f"{sys.executable} {install}"])
    first = run_task(bench.wb, TASK)
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"]), first.reason
    answer(bench, raw, "accept: the pin cannot be shown to discriminate")
    out = tdd.run_red(bench.wb, TASK, attempt=1)
    assert out.status == "already_satisfied", out.reason
    assert bench.events("criterion.pre_satisfied")[-1]["via"] == "human_override" and bench.events("check.accepted")


def test_minor_a_non_python_test_is_redacted_before_the_cut(make_bench):
    from l4.implementer import held_patch

    pem_body = "\n".join("MIIEowIBAAKCAQEA" + "x" * 48 for _ in range(20))
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{pem_body}\n-----END RSA PRIVATE KEY-----"
    bench = make_bench([])
    lines = (
        ["describe('loads key', () => {"]
        + ["  const a = 1;"] * 30
        + ["  const key = `" + pem + "`;"]
        + ["  const b = 2;"] * 30
        + ["});"]
    )
    (bench.wb.worktree / "tests" / "key.test.js").write_text("\n".join(lines) + "\n")
    shown = held_patch.test_source(bench.wb, "tests/key.test.js::loads key")
    assert "MIIEowIBAAKCAQEA" not in shown and "[cut: " in shown


def test_minor_capture_and_apply_ignore_the_operators_git_config(make_bench, monkeypatch, raw, tmp_path):
    config = tmp_path / "gitconfig"
    config.write_text("[diff]\n\tnoprefix = true\n\tmnemonicPrefix = true\n[color]\n\tui = always\n")
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [new_step(), renamed_step()])
    bench.wb.git.env["GIT_CONFIG_GLOBAL"] = str(config)  # the hold and the replay run under this configuration
    assert run_task(bench.wb, TASK).status == "blocked"
    data = patch_of(bench).read_bytes()
    assert data.startswith(b"diff --git a/") and b"\x1b[" not in data
    answer(bench, raw, "accept: fine")
    assert run_task(bench.wb, TASK).status == "done" and len(bench.adapter.requests) == 1


def test_minor_two_held_checks_on_one_task_leave_no_patch_tracked(make_bench, monkeypatch, raw):
    from .conftest import HEADER, STUB, UNKNOWN, UNKNOWN_TEST

    zero_says(monkeypatch)
    monkeypatch.setattr(
        tdd,
        "vacuity_check",
        lambda wb, zeroed, open_criteria, *, real=None: Vacuity(inconclusive={c: "ran no test" for c in open_criteria}),
    )
    step = Step(
        writes={
            "tests/test_new.py": NEW,
            "tests/test_discount.py": HEADER + UNKNOWN_TEST,
            "src/pytdd/pricing.py": STUB,
        },
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench = make_bench([step])
    assert run_task(bench.wb, TASK).question_ids == ["Q-001"]
    answer(bench, raw, "accept: fine")
    bench.wb.held_removals.clear()  # the next run has a new workbench
    second = run_task(bench.wb, TASK)
    assert second.question_ids == ["Q-002"] and bench.events("question.raised")[-1]["check"] == "vacuity"
    answer_q(bench, raw, "Q-002", "accept: run (b) cannot run here")
    bench.wb.held_removals.clear()
    assert tdd.run_red(bench.wb, TASK, attempt=1).status == "ok"
    assert not tracked(bench, patch_of(bench, "pre_satisfied")) and not tracked(bench, patch_of(bench, "vacuity"))


def test_minor_a_result_digest_is_required_whenever_a_patch_digest_is(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    sidecar = patch_of(bench).with_suffix(".json")
    meta = json.loads(sidecar.read_text())
    meta["result"]["notes_for_verifier"] = "TAMPERED"
    sidecar.write_text(json.dumps(meta, sort_keys=True))
    keep = ("id", "task", "kind", "title", "check", "criteria", "tests", "patch_sha256", "source_sha256")
    bench.writer.append(
        "question.raised", **{k: v for k, v in bench.events("question.raised")[-1].items() if k in keep}
    )
    commit_all(bench, raw, "tamper the sidecar, drop result_sha256")
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason
    assert bench.events("held.replayed") == [] and len(bench.adapter.requests) == 1


def test_minor_the_verified_bytes_are_what_is_applied(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine")
    assert run_task(bench.wb, TASK).status == "done"
    applies = [argv for argv in bench.wb.git.history if "apply" in argv]
    assert applies and all(argv[-1] == "-" for argv in applies), applies  # from stdin, never a re-read of the path


def test_minor_the_replay_commit_names_the_profile_that_wrote_the_patch(make_bench, monkeypatch, raw):
    from dataclasses import replace

    bench = held_new(make_bench, monkeypatch)
    writer = bench.wb.selected.profile_name
    answer(bench, raw, "accept: fine")
    bench.wb.selected = replace(bench.wb.selected, profile_name="another-profile")
    assert run_task(bench.wb, TASK).status == "done"
    body = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert f"L4-Agent: {writer}" in body and "another-profile" not in body


def test_minor_a_vacuity_hold_is_replayed_through_run_task(make_bench, monkeypatch, raw):
    from .conftest import green_step

    monkeypatch.setattr(
        tdd,
        "vacuity_check",
        lambda wb, zeroed, open_criteria, *, real=None: Vacuity(inconclusive={c: "ran no test" for c in open_criteria}),
    )
    bench: Bench = make_bench([red_step(), green_step()])
    first = run_task(bench.wb, GREEN_TASK)
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"]), first.reason
    answer(bench, raw, "accept: run (b) cannot run here")
    bench.wb.held_removals.clear()
    second = run_task(bench.wb, GREEN_TASK)
    assert second.status == "done", second.reason
    assert len(bench.adapter.requests) == 2  # red once (the hold), green once; the red step was replayed
    assert [e["check"] for e in bench.events("held.replayed")] == ["vacuity"]


# --- round 2: an accept takes effect only through the replay of exactly the saved step ----------------------------

STAND_IN = NEW.replace(
    "from pytdd import total\n",
    "def total(prices):  # a local stand-in: the test no longer calls the code under test\n    return 4.0\n",
)
CONFTEST_STAND_IN = (
    "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _stand_in(request, monkeypatch):\n"
    "    if request.module.__name__.endswith('test_new'):\n"
    "        monkeypatch.setattr(request.module, 'total', lambda prices: 4.0)\n"
)
SHADOWED = (
    NEW
    + '\n\n@pytest.mark.l4("'
    + KNOWN
    + '")\ndef test_new_total():  # the later def is the one pytest runs\n    assert True\n'
)


def later(**writes: str) -> Step:
    return Step(writes=writes, structured=result("red", criteria_ids=[KNOWN]))


@pytest.mark.parametrize(
    "writes",
    [
        {"tests/test_new.py": STAND_IN},
        {"tests/test_new.py": NEW, "tests/conftest.py": CONFTEST_STAND_IN},
        {"tests/test_new.py": SHADOWED},
    ],
    ids=["module-level-helper", "new-conftest", "second-def"],
)
def test_r1_after_a_used_up_replay_the_accept_covers_nothing_whatever_the_next_step_changed(
    make_bench, monkeypatch, raw, writes
):
    bench = held_new(make_bench, monkeypatch, [new_step(), later(**writes)])
    answer(bench, raw, "accept: fine")
    fail_lint_once(monkeypatch)
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason
    assert bench.events("task.done") == [] and len(bench.events("held.replayed")) == 1
    patch = patch_of(bench).read_bytes()  # the new hold saved the new step
    assert hashlib.sha256(patch).hexdigest() == bench.events("question.raised")[-1]["patch_sha256"]


def test_r1_a_used_up_accept_is_no_override_for_any_test_id(make_bench, monkeypatch, raw):
    from l4.implementer.held import accepted_overrides

    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine")
    assert accepted_overrides(bench.wb, "1.1", "pre_satisfied") == {}  # outside a replay: nothing
    fail_lint_once(monkeypatch)
    run_task(bench.wb, TASK)
    assert accepted_overrides(bench.wb, "1.1", "pre_satisfied") == {}  # after it: nothing, for Go or vitest ids alike
    assert accepted_overrides(bench.wb, "1.1", "at_red") == {}


def test_r1_a_replay_that_fails_a_gate_counts_as_an_attempt_and_the_cycle_is_bounded(make_bench, monkeypatch, raw):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [new_step(), new_step()], implementer={"max_task_attempts": 1})
    assert run_task(bench.wb, TASK).status == "blocked"
    answer(bench, raw, "accept: fine")
    monkeypatch.setattr(tdd, "worse_static_gates", lambda wb, base, phase: "lint got worse")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts (1)" in outcome.reason
    assert len(bench.events("task.attempt_failed")) == 1 and len(bench.adapter.requests) == 1


def test_r4_a_reopened_task_neither_covers_nor_replays_an_earlier_accept(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [new_step(), new_step()])
    bench.wb.emit("tasks.reopened", tasks=["1.1"])
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason  # the same body, still new
    assert bench.events("held.replayed") == [] and bench.events("check.accepted") == []


def test_r4_a_reopened_task_drops_the_accept_of_a_question_without_a_saved_step_too(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [new_step(), new_step()])
    old_style(bench)
    bench.wb.emit("tasks.reopened", tasks=["1.1"])
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason


def test_r2_the_question_shows_the_module_level_code_of_the_named_test_file(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch, [later(**{"tests/test_new.py": STAND_IN})])
    ctx = question_text(bench).split("### Context", 1)[1].split("### Options", 1)[0]
    assert "return 4.0" in ctx and "a local stand-in" in ctx  # the diff of the test file, not only the function
    answer(bench, raw, "accept: fine")
    assert run_task(bench.wb, TASK).status == "done"


def test_r2_a_cut_diff_says_the_cut_lines_are_replayed_too_and_where_the_whole_patch_is(make_bench, monkeypatch, raw):
    long_conftest = "".join(f"# line {n}\n" for n in range(45)) + CONFTEST_STAND_IN
    bench = held_new(make_bench, monkeypatch, [new_step(("tests/conftest.py", long_conftest))])
    ctx = question_text(bench).split("### Context", 1)[1].split("### Options", 1)[0]
    assert "_stand_in" not in ctx and "[cut: " in ctx
    assert "replayed too" in ctx and ".l4/held/1.1-pre_satisfied.patch" in ctx
    assert "the whole patch is in" in ctx
    answer(bench, raw, "accept: fine")
    assert run_task(bench.wb, TASK).status == "done"
    assert "_stand_in" in (bench.wb.worktree / "tests" / "conftest.py").read_text()


def test_r5_capture_and_apply_survive_diff_context_zero_and_autocrlf(make_bench, tmp_path):
    from l4.implementer import held_patch
    from l4.implementer.held import HeldCheck

    config = tmp_path / "gitconfig"
    config.write_text("[diff]\n\tcontext = 0\n[core]\n\tautocrlf = true\n")
    bench: Bench = make_bench([])
    wb = bench.wb
    wb.git.env["GIT_CONFIG_GLOBAL"] = str(config)
    target = wb.worktree / "README.md"
    target.write_text("one\n\ntwo\n\nthree\n")
    wb.git.run("add", "README.md")
    wb.commit("docs: readme", task="0.1", attempt=1, phase="red", tdd=None)
    target.write_text("one\n\nTWO\n\nthree\n")
    held = held_patch.capture(wb, HeldCheck("1.1", "red", "pre_satisfied", (KNOWN,), (), "why"), None)
    assert (
        held.patch is not None and b"@@ -1,5 +1,5 @@" in held.patch
    )  # three lines of context, whatever diff.context says
    wb.git.run("checkout", "HEAD", "--", ".", config=[("core.autocrlf", "false")])  # back to the bytes of the base
    check = wb.git.run_input_bytes(
        *held_patch.GIT_PLAIN, *held_patch.APPLY_FLAGS, "--check", "-", data=held.patch, check=False
    )
    assert check.returncode == 0, check.stderr
