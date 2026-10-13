"""Item records from one unit's evidence (M16-G12, join line 28): the one builder both the canary and a live run
call, so the same unit gets the same project key, the same states and therefore the same split."""

import hashlib
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from l4.config.schema import L4Config
from l4.evidence.collect import Evidence, show_blob
from l4.evidence.diffcov import ChangedFunction, changed_functions, diff_lines
from l4.gates.junit import TestReport
from l4.redact import Redactor
from l4.s1 import questions as q
from l4.s1 import states
from l4.s1.records import ItemRecord, Origin, item_key, unit_hash
from l4.vcs.git import Git


def project_key(git: Git, fallback: str) -> str:
    """A name for the repository that does not depend on the directory it is cloned into: its root commit."""
    done = git.run("rev-list", "--max-parents=0", "HEAD", check=False)
    roots = sorted(done.stdout.split()) if done.returncode == 0 else []
    return f"git-{roots[0][:12]}" if roots else fallback


def _instruction(set_name: str) -> str:
    return max((x.instructions for x in q.get_set(set_name).questions), key=len)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_keys_by_subject(items: Sequence[ItemRecord]) -> dict[str, str]:
    """`<question set>|<subject>` -> item_key, the table `Evidence.item_keys` carries into evidence.json."""
    return {f"{i.question_set}|{i.subject}": i.item_key for i in items}


def items_from_evidence(
    ev: Evidence,
    *,
    git: Git,
    cfg: L4Config,
    redactor: Redactor,
    project: str,
    unit_id: str,
    unit_name: str,
    spec_dir: str,
    base: str,
    head: str,
    report: TestReport,
    new_tests: Collection[str],
    origin: Origin,
    run_id: str,
    round: int,
    tags: Sequence[str] = (),
) -> list[ItemRecord]:
    """One item per labelled file, changed function and test run of `ev`; the ground truth is `ev` and nothing else."""
    # code, tests and the proposal come from git blobs (`git show <sha>:<path>`), as in `collect.py`: the worktree may
    # hold a symlink or an edit that is not part of the commit. The spec is read at `base`, like the declared scope.
    proposal = show_blob(git, base, f"{spec_dir}/proposal.md") or ""
    spec = states.spec_summary(unit_name, proposal)
    budget = cfg.verifier.s1.laya_budget()
    all_tags = [f"origin:{origin}", f"project:{project}", *tags]  # tags are metadata: never in a state or a key
    test_paths = [f.path for f in ev.scope.files if f.kind == "test"]
    test_sources = {p: t for p in test_paths if (t := show_blob(git, head, p)) is not None}
    items: list[ItemRecord] = []

    def add(set_name: str, subject: str, state: states.State, truth: Mapping[str, Any], source: str) -> None:
        text = redactor.redact_text(state.text)
        sha = _sha(text)
        items.append(
            ItemRecord(
                item_key=item_key(project, unit_id, set_name, subject, sha),
                unit=unit_id,
                unit_hash=unit_hash(project, unit_id),
                project=project,
                run_id=run_id,
                round=round,
                origin=origin,
                subject=subject,
                state=text,
                state_sha256=sha,
                question_set=set_name,
                question_sha256=q.get_set(set_name).sha256,
                expected=q.expected_for(set_name, truth),
                label_source=source,
                tags=sorted({*all_tags, *(["truncated"] if state.truncated else [])}),
            )  # fmt: skip
        )

    file_instr = _instruction(q.FILE_RELEVANT)
    for fs in ev.scope.files:
        if fs.label is None or fs.kind not in ("code", "test"):
            continue
        diff = git.run("diff", "--no-color", "-U1", base, head, "--", fs.path, check=False).stdout
        state = states.file_state(
            spec, fs.path, states.hunk_summary(diff), instruction=file_instr, budget=budget, declared=ev.scope.declared
        )  # fmt: skip
        named = fs.reason == "named in the spec" if fs.kind == "code" else None
        truth = {"relevant": fs.label == "relevant", "named": named}
        add(q.FILE_RELEVANT, fs.path, state, truth, "deterministic:scope")

    cov = ev.coverage
    if cov is not None:
        kinds = {f.path: f.kind for f in ev.scope.files}
        lines = diff_lines(git, base, head, exclude=lambda p: kinds.get(p) in ("test", "exempt"))
        funcs: dict[tuple[str, str], ChangedFunction] = {}
        for path, changed in lines.items():
            for cf in changed_functions(path, show_blob(git, head, path) or "", set(changed)):
                funcs[(cf.path, cf.qualname)] = cf
        names = sorted(report.tests)
        func_instr = _instruction(q.CHANGE_COVERED)
        for fc in cov.functions:
            cf = funcs.get((fc.path, fc.qualname))
            if fc.label is None or cf is None:
                continue
            source = (show_blob(git, head, fc.path) or "").splitlines()
            signature = source[cf.span[0] - 1] if fc.qualname != "<module>" and cf.span[0] <= len(source) else ""
            changed_text = "\n".join(source[n - 1] for n in sorted(cf.lines) if n <= len(source))
            state = states.function_state(
                fc.path, fc.qualname, f"{signature}\n{changed_text}".strip(), names,
                states.static_mentions(fc.qualname, test_sources), instruction=func_instr, budget=budget,
            )  # fmt: skip
            truth = {"covered": fc.label, "executed": fc.executed, "executable": fc.executable}
            add(q.CHANGE_COVERED, f"{fc.path}::{fc.qualname}", state, truth, "deterministic:diff-coverage")

    if ev.ran is not None:
        s = ev.ran.summary
        counts = {"total": s.total, "passed": s.passed, "failed": s.failed, "errored": s.errored, "skipped": s.skipped}
        listed = [(i, report.tests[i].status if i in report.tests else "missing") for i in sorted(new_tests)]
        problems = [
            (i, c.status) for i, c in sorted(report.tests.items()) if c.status != "passed" and i not in new_tests
        ]
        instruction = _instruction(q.TESTS_OK)
        state = states.tests_state(counts, listed, problems=problems, instruction=instruction, budget=budget)
        add(q.TESTS_OK, "tests", state, {"tests_ok": ev.ran.all_passed}, "deterministic:tests-ran")
    return items
