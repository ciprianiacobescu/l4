# ruff: noqa: F811
"""The review re-entry of SPEC 12.0 end to end (M1.9, G1 and G2): `l4 run` with a scripted fake agent, a fake GitLab and
a bare origin. A unit in `in_review` takes the edge of the commit that followed H, runs a full round, and is handed off
again with a new H."""

import json

import pytest

from l4.agents.fake import Step
from l4.specs.criteria import openspec_criteria

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..conftest import FIXTURE
from ..implementer.conftest import green_step, red_step
from ..verifier.conftest import judge_reply, openspec_stand_in, valid_spec  # noqa: F401
from .conftest import BRANCH, UNIT_DIR

HANDOFF = "docs(add-discount-codes): hand off to review"
CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
JUDGE = Step(structured=judge_reply(CRITERIA))


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on: this file is about what happens after its PASS (overrides the orchestrator suite's)."""


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on: a FAIL on the re-entry round goes on into fix tasks in the same run."""


def human_commit(tdd, raw, files: dict[str, str], message: str = "human fix", *, name: str = "human") -> str:
    """What a person does: clone the remote, commit on the unit branch (no `L4-Run`, not the bot), push, fetch."""
    clone = tdd.repo.parent / name
    raw(tdd.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd.origin), str(clone))
    for rel, text in files.items():
        (clone / rel).parent.mkdir(parents=True, exist_ok=True)
        (clone / rel).write_text(text)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", message)
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd.repo, "fetch", "-q", "origin")
    return raw(clone, "rev-parse", "HEAD").strip()


@pytest.fixture
def in_review(run_l4, valid_spec, forge_env, use_fake_gitlab):
    first = run_l4([red_step(), green_step(), JUDGE])
    assert first.code == 0 and first.outcome["units"][0]["phase_after"] == "in_review"
    return first


def test_human_code_commit_after_handoff_reverifies_and_hands_off_again(
    in_review, run_l4, tdd_repo, raw, use_fake_gitlab
):
    """SCN-ARC-16, `post_merge_pr` form."""
    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    pricing = raw(tdd_repo.origin, "show", f"{BRANCH}:src/pytdd/pricing.py")
    human = human_commit(tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n# tidied by a person\n"})
    second = run_l4([JUDGE])
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:] if second.adapter.requests else ""
    changes = [(e["from"], e["to"], e["trigger"]) for e in second.events("phase.changed")][-3:]
    assert changes == [
        ("in_review", "verifying", "commit_after_handoff"),
        ("verifying", "verified", "verify_pass"),
        ("verified", "in_review", "hand_off_pushed"),
    ]
    edge = [e for e in second.events("phase.changed") if e["trigger"] == "commit_after_handoff"][0]
    assert edge["handoff"] == h1 and [c["sha"] for c in edge["commits"]] == [human]
    # a new round whose subject is the human commit
    verdicts = second.events("verify.verdict")
    assert [v["round"] for v in verdicts] == [1, 2] and verdicts[-1]["verdict"] == "PASS"
    assert {e["subject_sha"] for e in second.events("verify.step") if e["round"] == 2} == {human}
    # H2 is the MR head, with the human commit in its history and no `[skip ci]`
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    assert head != h1 and raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    assert raw(tdd_repo.origin, "merge-base", "--is-ancestor", human, head) == ""
    assert raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines().count(HANDOFF) == 2
    assert not use_fake_gitlab.mrs[1]["title"].lower().startswith("draft")
    assert second.outcome["units"][0]["phase_before"] == "in_review"


def test_a_bot_identity_commit_after_h_reverifies(in_review, run_l4, tdd_repo, raw, use_fake_gitlab):
    """SCN-YOLO-100, run side: a commit that copies the bot's identity and an `L4-Run` trailer is still a commit after
    the recorded H (L4-ARC-008), so the unit is verified again."""
    from l4.vcs.git import BOT_IDENTITY

    clone = tdd_repo.repo.parent / "forger"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    (clone / "src/pytdd").mkdir(parents=True, exist_ok=True)
    (clone / "src/pytdd/forged.py").write_text("x = 1\n")
    raw(clone, "add", "-A")
    raw(
        clone, "-c", f"user.name={BOT_IDENTITY.name}", "-c", f"user.email={BOT_IDENTITY.email}", "commit", "-q",
        "-m", "chore: tidy\n\nL4-Run: r-20261014T1000Z-0002",
    )  # fmt: skip
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    second = run_l4([JUDGE])
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:] if second.adapter.requests else ""
    changes = [(e["from"], e["to"], e["trigger"]) for e in second.events("phase.changed")][-3:]
    assert changes == [
        ("in_review", "verifying", "commit_after_handoff"),
        ("verifying", "verified", "verify_pass"),
        ("verified", "in_review", "hand_off_pushed"),
    ]


def test_reentry_sets_the_mr_back_to_draft_before_any_push(
    in_review,
    run_l4,
    tdd_repo,
    raw,
    use_fake_gitlab,
    monkeypatch,
):
    """L4-ARC-008 (c): the MR is a draft again, with its labels, before the run pushes anything."""
    from l4.forge.gitlab import GitLabForge
    from l4.vcs.git import Git

    order: list[str] = []
    real_route, real_push = use_fake_gitlab.route, Git.push_branch

    def route(method, path, query, body):
        if method == "PUT" and body and str(body.get("title", "")).startswith("Draft: "):
            order.append("mr draft")
        return real_route(method, path, query, body)

    def push(self, remote, branch, *, config=(), answers=None):
        order.append("push")
        return real_push(self, remote, branch, config=config, answers=answers)

    monkeypatch.setattr(use_fake_gitlab, "route", route)
    monkeypatch.setattr(Git, "push_branch", push)
    assert not use_fake_gitlab.mrs[1]["title"].startswith("Draft: ")  # ready after the hand-off
    pricing = raw(tdd_repo.origin, "show", f"{BRANCH}:src/pytdd/pricing.py")
    human_commit(tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n# tidied\n"})
    assert run_l4([JUDGE]).code == 0
    assert order[0] == "mr draft" and "push" in order, order
    assert order.index("mr draft") < order.index("push")
    assert GitLabForge  # the fake serves the real forge class


def test_sticky_note_names_the_foreign_commits_or_the_red_jobs(
    in_review,
    run_l4,
    tdd_repo,
    raw,
    use_fake_gitlab,
):
    pricing = raw(tdd_repo.origin, "show", f"{BRANCH}:src/pytdd/pricing.py")
    human = human_commit(tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n# tidied\n"}, "tidy the pricing module")
    assert run_l4([JUDGE]).code == 0
    # the sticky note is rewritten in place: its history is in the PUTs of the fake
    bodies = [b["body"] for m, p, q, b in use_fake_gitlab.requests if m in ("POST", "PUT") and b and "body" in b]
    first = next(body for body in bodies if "Re-verifying after the hand-off" in body)
    assert human[:10] in first and "tidy the pricing module" in first and "commit_after_handoff" in first
    assert "Nothing is waiting for a human answer." in bodies[-1]  # handed off again: the section is gone


def snapshot_of_remote(tdd, raw, use_fake_gitlab) -> tuple[str, int]:
    """Every ref of the origin (the unit branch and the lock ref) and the number of forge writes."""
    return raw(tdd.origin, "for-each-ref"), len(use_fake_gitlab.writes())


def bot_commit(tdd, raw, *, run: bool, name: str) -> str:
    """A commit on the unit branch by the bot identity, with or without the `L4-Run` trailer."""
    clone = tdd.repo.parent / name
    raw(tdd.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd.origin), str(clone))
    (clone / "bot.txt").write_text(name)
    raw(clone, "add", "-A")
    trailers = ["--trailer=L4-Run: r-20261005T0000Z-0000", "--trailer=L4-Phase: implementing"] if run else []
    raw(clone, "-c", "user.name=l4-bot", "-c", "user.email=l4-bot@users.noreply.invalid", "commit", "-q",
        "-m", f"bot commit ({name})", *trailers)  # fmt: skip
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd.repo, "fetch", "-q", "origin")
    return raw(clone, "rev-parse", "HEAD").strip()


def test_the_harness_never_retriggers_itself(in_review, run_l4, tdd_repo, raw, use_fake_gitlab):
    """L4-ARC-008 (d) and decision 11: the new hand-off commit is the recorded H, so only a commit after the recorded H
    starts a round, and every such commit does, whatever identity it claims (SCN-YOLO-100)."""
    pricing = raw(tdd_repo.origin, "show", f"{BRANCH}:src/pytdd/pricing.py")
    human_commit(tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n# tidied\n"})
    assert run_l4([JUDGE]).code == 0
    # after H2 a run says `nothing to do`: no commit, push, MR write or lock-ref commit
    before = snapshot_of_remote(tdd_repo, raw, use_fake_gitlab)
    third = run_l4([], unit=False)
    assert third.code == 0 and third.adapter.requests == []
    assert snapshot_of_remote(tdd_repo, raw, use_fake_gitlab) == before
    # a bot commit with `L4-Run` after the recorded H is foreign: it re-verifies (it used to be the harness's)
    forged = bot_commit(tdd_repo, raw, run=True, name="bot-with-run")
    fourth = run_l4([JUDGE], unit=False)
    assert fourth.code == 0
    edge = [e for e in fourth.events("phase.changed") if e["trigger"] == "commit_after_handoff"][-1]
    assert [c["sha"] for c in edge["commits"]] == [forged]
    # an `l4-bot`-named commit without `L4-Run` is foreign too: it re-verifies
    sneaky = bot_commit(tdd_repo, raw, run=False, name="bot-without-run")
    fifth = run_l4([JUDGE], unit=False)
    assert fifth.code == 0
    edge = [e for e in fifth.events("phase.changed") if e["trigger"] == "commit_after_handoff"][-1]
    assert [c["sha"] for c in edge["commits"]] == [sneaky]


@pytest.fixture
def one_fix_round(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from ..conftest import TddRepo

    original = TddRepo.config

    def config(self, **kw):
        body = yaml.safe_load(original(self, **kw))
        body["verifier"] = {**body.get("verifier", {}), "max_fix_rounds": 1}
        return yaml.safe_dump(body)

    monkeypatch.setattr(TddRepo, "config", config)


def test_a_fix_round_that_cannot_fix_ends_in_escalated_after_max_fix_rounds(
    one_fix_round, in_review, run_l4, tdd_repo, raw
):
    """A person's commit that breaks the lint gate, and a fix task that leaves it broken: bounded by max_fix_rounds.
    (It used a person's undeclared `# noqa` before W-D6: that is the owner's edit now, listed, not a finding.)"""
    from ..implementer.conftest import IMPL, result

    lint = ["sh -c '! grep -q BROKEN src/pytdd/pricing.py'"]  # a lint gate: the word BROKEN may not appear
    human_commit(tdd_repo, raw, {"src/pytdd/pricing.py": IMPL + "\nBROKEN = 1\n"}, "break the linter")
    still_bad = Step(writes={"src/pytdd/pricing.py": IMPL + "\nBROKEN = 2\n"}, structured=result("single"))
    run = run_l4([still_bad], lint=lint)
    assert run.code == 13
    assert run.outcome["units"][0]["phase_after"] == "escalated"
    assert [v["verdict"] for v in run.events("verify.verdict")][-2:] == ["FAIL", "FAIL"]
    assert run.triggers()[-1] == "verify_fail_exhausted"


def test_spec_edit_after_handoff_goes_to_implementing(in_review, run_l4, tdd_repo, raw, use_fake_gitlab):
    """A person adds a task to the unit after the hand-off: it is implemented, verified, and handed off again."""
    from ..implementer.conftest import HEADER, IMPL, KNOWN, result

    tasks = raw(tdd_repo.origin, "show", f"{BRANCH}:{UNIT_DIR}/tasks.md")
    added = '- [ ] 1.2 Add `describe_code(code)` to `src/pytdd/pricing.py` implementing requirement "Discount codes"\n'
    human = human_commit(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": tasks + added}, "add a task")
    test = HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_describe():\n    from pytdd.pricing import describe_code\n\n'
    test += '    assert describe_code("SAVE10") == "10% off"\n'
    red = Step(
        writes={
            "tests/test_describe.py": test,
            "src/pytdd/pricing.py": IMPL + "\n\ndef describe_code(code):\n    raise NotImplementedError\n",
        },
        structured=result("red", task_ids=["1.2"], tests_added=["tests/test_describe.py::test_describe"],
                          criteria_ids=[KNOWN]),
    )  # fmt: skip
    describe = IMPL + '\n\ndef describe_code(code):\n    return f"{CODES[code]}% off"\n'
    green = Step(writes={"src/pytdd/pricing.py": describe}, structured=result("green", task_ids=["1.2"]))
    run = run_l4([red, green, JUDGE])
    assert run.code == 0, run.adapter.requests[-1].prompt[-500:]
    assert run.triggers()[-5:] == [
        "spec_edit_after_handoff", "all_leaves_done", "verification_started", "verify_pass", "hand_off_pushed",
    ]  # fmt: skip
    edge = [e for e in run.events("phase.changed") if e["trigger"] == "spec_edit_after_handoff"][0]
    assert edge["to"] == "implementing" and [c["sha"] for c in edge["commits"]] == [human]
    assert [e["task"] for e in run.events("task.done")][-1] == "1.2"
    assert raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    assert not use_fake_gitlab.mrs[1]["title"].lower().startswith("draft")


def test_ci_failure_on_h_runs_a_round_that_fails_at_step_0_and_spawns_a_fix_unit(
    in_review, run_l4, tdd_repo, raw, use_fake_gitlab, monkeypatch
):
    """SCN-ARC-14 end to end: a sweep against a red pipeline on H, then `l4 run`. The round fails at step 0 with
    `repository CI failed: test`, the judge is not called, and a `[chore]` fix task names the job and carries the tail.
    After the fix a full round passes, H2 is handed off, and a green sweep on H2 writes nothing."""
    from l4.ci import sweeper
    from l4.cli import main
    from l4.forge.gitlab import GitLabForge

    from ..archive.conftest import API, PROJECT, TOKEN
    from ..implementer.conftest import IMPL, result

    fake = use_fake_gitlab
    monkeypatch.setattr(
        sweeper, "make_forge",
        lambda cfg, environ, **kw: GitLabForge(API, PROJECT, TOKEN, transport=fake.transport(), sleep=lambda s: None),
    )  # fmt: skip

    def sweep() -> int:
        return main(["plan", "--sweep", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)

    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    tail = "\n".join(f"line {i}" for i in range(60)) + "\nE   assert 1 == 2\nFAILED tests/test_pricing.py::test_total"
    fake.add_pipeline(h1, [("test", "failed", {"trace": tail}), ("l4", "success")])
    assert sweep() == 0
    assert [e["type"] for e in in_review.events("ci.failed")] == ["ci.failed"]
    chore = Step(writes={"src/pytdd/pricing.py": IMPL + "\n# make the CI job pass\n"}, structured=result("single"))
    run = run_l4([chore, JUDGE])
    assert run.code == 0, run.adapter.requests[-1].prompt[-500:]
    assert run.triggers()[-5:] == [
        "repository_ci_failed", "verify_fail_fix", "fix_unit_done", "verify_pass", "hand_off_pushed",
    ]  # fmt: skip
    edge = [e for e in run.events("phase.changed") if e["trigger"] == "repository_ci_failed"][0]
    assert edge["head"] == h1 and [j["name"] for j in edge["jobs"]] == ["test"]
    assert [v["verdict"] for v in run.events("verify.verdict")] == ["PASS", "FAIL", "PASS"]
    [ci_step] = run.events("ci.step")  # M1.10: the log names no step, so it is skipped with that reason
    assert ci_step["status"] == "skipped" and "no failing step in the log" in ci_step["reason"]
    steps = {s["step"]: s["status"] for s in run.events("verify.step") if s["round"] == 2}
    assert steps == {"0": "failed", "10": "ok"}  # step 0 failed, nothing ran between it and the report
    assert len(run.events("verify.judge")) == 2  # the first PASS and the last: the failed round never reached the judge
    [spawned] = run.events("fix.spawned")
    fix_dir = f"{BRANCH}:openspec/changes/{spawned['fix_unit']}"
    assert "1.1 repository CI failed: test" in raw(tdd_repo.origin, "show", f"{fix_dir}/tasks.md")
    marker = json.loads(raw(tdd_repo.origin, "show", f"{fix_dir}/.l4/fix.json"))
    assert marker["chores"] == spawned["findings"]  # a [chore] task: one agent step, no red phase
    proposal = raw(tdd_repo.origin, "show", f"{fix_dir}/proposal.md")  # the task's finding, with the end of the log
    assert "job `test`" in proposal and "FAILED tests/test_pricing.py::test_total" in proposal
    h2 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    assert h2 != h1 and raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    # a green sweep on H2 writes nothing
    fake.add_pipeline(h2, [("test", "success")])
    refs, writes = raw(tdd_repo.origin, "for-each-ref"), len(fake.writes())
    assert sweep() == 0
    assert raw(tdd_repo.origin, "for-each-ref") == refs and len(fake.writes()) == writes


def test_no_committed_object_names_the_forge_host_after_a_ci_reentry(
    in_review, run_l4, tdd_repo, raw, use_fake_gitlab, monkeypatch, capsys
):
    """P5 over a whole fake run, CI re-entry included: no blob reachable from any ref of the origin (branch, lock ref)
    and no commit message names the forge host, although the job log and the job URL do; the console keeps the link."""
    from l4.ci import sweeper
    from l4.cli import main
    from l4.forge.gitlab import GitLabForge

    from ..archive.conftest import API, PROJECT, TOKEN
    from ..forge.conftest import WEB
    from ..implementer.conftest import IMPL, result

    fake = use_fake_gitlab
    monkeypatch.setattr(
        sweeper, "make_forge",
        lambda cfg, environ, **kw: GitLabForge(API, PROJECT, TOKEN, transport=fake.transport(), sleep=lambda s: None),
    )  # fmt: skip
    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    tail = f"Fetching {WEB}.git\nsee {WEB}/-/jobs/1001/artifacts\nFAILED tests/test_pricing.py::test_total"
    fake.add_pipeline(h1, [("test", "failed", {"trace": tail})])
    assert main(["plan", "--sweep", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    chore = Step(writes={"src/pytdd/pricing.py": IMPL + "\n# make the CI job pass\n"}, structured=result("single"))
    run = run_l4([chore, JUDGE])
    assert run.code == 0 and run.triggers()[-1] == "hand_off_pushed"
    host = "gitlab.example.test"
    blobs = {
        line.split()[0]
        for line in raw(tdd_repo.origin, "rev-list", "--all", "--objects").splitlines()
        if raw(tdd_repo.origin, "cat-file", "-t", line.split()[0]).strip() == "blob"
    }
    leaking = [b for b in blobs if host in raw(tdd_repo.origin, "cat-file", "-p", b)]
    named = {
        path
        for ref in raw(tdd_repo.origin, "for-each-ref", "--format=%(refname)").split()
        for path in raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", ref).split()
        if host in raw(tdd_repo.origin, "show", f"{ref}:{path}")
    }
    assert leaking == [] and named == set(), named
    assert host not in raw(tdd_repo.origin, "log", "--all", "--format=%B")
    assert "<forge>/example-group/dummy-agentic/-/jobs/" in raw(tdd_repo.origin, "log", "-p", "--all")  # it was there
    assert WEB in capsys.readouterr().err  # the console trace keeps the link


# --- M1.10 line 9: a wrong CI fix is caught by the repository CI gate (SCN-ARC-14, C1) ---

CHECK_LEN = (
    "import pathlib, sys\n"
    "bad = [(p, n, len(line)) for p in sorted(pathlib.Path(sys.argv[1]).rglob('*.py'))\n"
    "       for n, line in enumerate(p.read_text().splitlines(), 1) if len(line) > 92]\n"
    "for p, n, size in bad:\n    print(f'E501 Line too long ({size} > 92) at {p}:{n}')\n"
    "sys.exit(1 if bad else 0)\n"
)
LONG_NOTICE = (
    'NOTICE = "' + "Unused items may be returned within thirty days of delivery for a full refund. " * 2 + '"\n'
)


@pytest.fixture
def ci_on_main(tdd_repo, raw):
    """The project's CI file and its check script are on main, as they are in a real project; the long line too."""
    import sys

    files = {
        ".gitlab-ci.yml": f"test:\n  stage: test\n  script:\n    - {sys.executable} scripts/check_len.py src\n",
        "scripts/check_len.py": CHECK_LEN,
        "src/pytdd/notice.py": LONG_NOTICE,
    }
    for name, text in files.items():
        (tdd_repo.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (tdd_repo.repo / name).write_text(text)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "ci: a length check")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")


def test_a_wrong_ci_fix_is_caught_by_the_repository_ci_gate(
    ci_on_main, in_review, run_l4, tdd_repo, raw, use_fake_gitlab, monkeypatch
):
    """The red pipeline's job fails on `<python> scripts/check_len.py src`, a script of the repository named in its
    `.gitlab-ci.yml`. The chore first leaves a long line: L4's own gate `repository-ci:test` fails and the retry fixes
    it. The trace and ledger show `ci.step` derived then reproduced, and the round after the chore runs it again."""
    import sys

    from l4.ci import sweeper
    from l4.cli import main
    from l4.forge.gitlab import GitLabForge

    from ..archive.conftest import API, PROJECT, TOKEN
    from ..implementer.conftest import IMPL, result

    fake = use_fake_gitlab
    monkeypatch.setattr(
        sweeper, "make_forge",
        lambda cfg, environ, **kw: GitLabForge(API, PROJECT, TOKEN, transport=fake.transport(), sleep=lambda s: None),
    )  # fmt: skip
    command = f"{sys.executable} scripts/check_len.py src"
    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    trace = (
        "section_start:1:step_script\r\x1b[0KExecuting step_script\n"
        f"$ {command}\n"
        f"E501 Line too long ({len(LONG_NOTICE) - 1} > 92) at src/pytdd/notice.py:1\n"
        "section_end:2:step_script\r\x1b[0K\nERROR: Job failed: exit code 1\n"
    )
    fake.add_pipeline(h1, [("test", "failed", {"trace": trace}), ("l4", "success")])
    assert main(["plan", "--sweep", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    [failed] = in_review.events("ci.failed")
    assert failed["jobs"][0]["step"] == command  # the sweep read it from the step_script section
    wrong = Step(writes={"src/pytdd/notice.py": LONG_NOTICE.replace("Unused", "Used"), "src/pytdd/pricing.py": IMPL},
                 structured=result("single"))  # fmt: skip
    right = Step(
        writes={"src/pytdd/notice.py": 'NOTICE = "Unused items may be returned."\n'}, structured=result("single")
    )
    run = run_l4([wrong, right, JUDGE])
    assert run.code == 0, run.adapter.requests[-1].prompt[-800:]
    steps = run.events("ci.step")
    assert [(s["status"], s["job"]) for s in steps] == [("derived", "test"), ("reproduced", "test")]
    assert (
        steps[0]["command"] == command and steps[0]["head"] == h1 and steps[0]["source"] == f".gitlab-ci.yml@{h1[:10]}"
    )
    gates = [(e["name"], e["status"]) for e in run.events("gate.finished") if e["name"] == "repository-ci:test"]
    assert gates == [
        ("repository-ci:test", "fail"),  # the chore's reproduction at its base
        ("repository-ci:test", "fail"),  # attempt 1 leaves the long line
        ("repository-ci:test", "pass"),  # attempt 2
        ("repository-ci:test", "pass"),  # round n+1, step 2
    ]  # fmt: skip
    assert [v["verdict"] for v in run.events("verify.verdict")] == ["PASS", "FAIL", "PASS"]
    assert run.triggers()[-5:] == [
        "repository_ci_failed", "verify_fail_fix", "fix_unit_done", "verify_pass", "hand_off_pushed",
    ]  # fmt: skip
    assert "repository-ci:test still fails" in run.adapter.requests[1].prompt  # the retry names the failing gate
    assert "E501 Line too long" in run.adapter.requests[1].prompt
    h2 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    assert h2 != h1 and raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
