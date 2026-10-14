Every line is test-first: write the test, see it fail for the stated reason, then write the code. Implementers work
from this file and design.md; the review in 8.1 is independent. No line edits a module on a run path (L4-KG-001).

## 1. Index core (wave 1, agent A: `src/l4/kg/__init__.py`, `kg/model.py`, `kg/store.py`, `kg/normalise.py`, `tests/unit/kg/test_model.py`, `test_store.py`, `test_normalise.py`)

- [x] 1.1 `Node` and `Edge` frozen dataclasses (D4), and a canonical JSONL writer: sorted keys, sorted lines, LF, UTF-8, `ensure_ascii=False`. Test: two writes of the same set in a different order are byte-identical. (L4-KG-003, SCN-KG-04)
- [x] 1.2 `store.index_dir(app)`: `cache_root(app.environ, repo=app.repo) / "kg" / <16 hex of sha256(resolved repo)>`, created with mode 0700. The `L4Exit(USAGE_ERROR)` of `cache_root` passes through. Tests: SCN-KG-05; two repositories get two folders (part of SCN-KG-23). (L4-KG-003, L4-KG-011)
- [x] 1.3 `store.write_index` and `store.read_index`: each file through `atomic_write_bytes`, `manifest.json` (`l4/kg-manifest@1`: harness version, sorted `refs`, counts, `skipped`, the sha256 of the two data files) last, and no build time. `read_index` returns `missing`, `incomplete` (a sha256 mismatch) or `stale` (a ref now points elsewhere). Test: SCN-KG-03 with a fault injected between the renames. (L4-KG-002, L4-KG-003)
- [x] 1.4 `normalise.norm`, `recurrence_key(title, alias, framework)` and `failure_class(reason)` with D5's rules. Table tests with the live reasons of design D5 and D7 (`no new test traces C-e25f06d8: …` → `no new test traces <criterion>`; the lint-gate reason; `new tests fail with an error that is neither …: tests.…`; `the agent step ended with status error: …`), a Kiro alias (empty second part), and no criterion. (L4-KG-006, the key parts of SCN-KG-12 and SCN-KG-13)

## 2. Sources (wave 1, agent B: `kg/sources.py`, `tests/unit/kg/test_sources.py`, `tests/unit/kg/conftest.py` with the fixture-repository builder and the recording `Git`)

- [x] 2.1 The fixture builder: a temp git repository with an `origin` bare remote, a base branch, OpenSpec and Kiro unit folders, ledgers and `verdict.json` files written with the real writers (`LedgerWriter` or `parse_ledger_files`-valid lines, `verdict_json`), unit branches, a lock ref with a pending ledger, and attempts refs. The recording `Git` keeps every argv and fails on any subcommand outside D1's list. (L4-KG-001)
- [x] 2.2 The base walker: `changes/<name>/`, every `changes/archive/<date>-<name>/` (its own `ls-tree` walk; not `list_units`, which skips `archive/`, and not `archive_folders`, which keeps only the newest per name), and `.kiro/specs/<name>/`, all read at `refs/remotes/origin/<base>` (else `HEAD` with a warning) through `regular_blobs` and `cat-file`. Test: SCN-KG-06 (the archive part). (L4-KG-004)
- [x] 2.3 Unit branches: `for-each-ref refs/remotes/origin/<branch_prefix>`, `parse_unit_id`, the unit folder plus `<name>-fix-<n>` siblings, and the local lock ref merged with `merge_ledgers` (as `state/status.py:load_snapshot`). Test: SCN-KG-06 (the branch part). (L4-KG-004)
- [x] 2.4 Attempts: the local `refs/l4/attempts/<fw>/<name>/<n>` as attempt `n`, and the current branch as attempt 0. A `unit.restarted{attempt_ref}` with no local ref is counted as `attempt_not_local`. Tests: SCN-KG-07, SCN-KG-09 (no `fetch` in the recorded argv). (L4-KG-004)
- [x] 2.5 Skips by reason (`ledger_corrupt`, `verdict_unreadable`, `oversize`, `not_regular`, `lessons_problem`, `error`), never fatal. An exception inside one unit skips that unit. Test: SCN-KG-08. (L4-KG-002, L4-KG-004)
- [x] 2.6 The lessons at the base ref: `memory.lessons_file` and `_archive/*.md` through `parse_lessons`. A file with problems is counted as `lessons_problem`, and its parsed lessons are still used. (L4-KG-004)

## 3. Promote (wave 1, agent C: `src/l4/memory/inbox.py`, `src/l4/memory/promote.py`, `run_lessons` in `src/l4/memory/cli.py`, `tests/unit/memory/test_inbox.py`, `tests/unit/memory/test_promote.py`)

- [x] 3.1 `inbox.find_proposal(repo, lid, from_dir)`: `.serena/memories/inbox/*/<lid>.md`. None → exit 2; more than one → exit 2 listing them, unless `--from`; `reject_symlinks` and `read_regular_file(limit=256 KiB)`. `inbox.parse_proposal`: exactly one v1 section through `parse_lessons`; the id equals `lesson_id(dedupe key)` (the message names the expected id); `valid_glob` for every glob; refuse a `TODO(person):` line or an empty body. (L4-KG-013)
- [x] 3.2 `promote.check_checkout`: refuse with exit 2 when `memory.enabled` is false, HEAD is detached or on a branch under `forge.branch_prefix`, anything is staged, the work-tree lessons file differs from HEAD, the current lessons file has parse problems, or `git var GIT_AUTHOR_IDENT` fails. One test per refusal, each showing that nothing was written. Tests: SCN-KG-28, SCN-KG-29. (L4-KG-013)
- [x] 3.3 `promote.promote(app, cfg, lid, *, from_dir, yes, commit)`: print the lesson and `scope: <globs>` or `scope: every task`. Ask on a terminal; with no terminal and no `--yes`, exit 2. Then `apply_candidates(repo, cfg.memory, [LessonCandidate(…, origin="human_edit")], writer=None)`, and print the archived ids. An existing dedupe key reinforces (SCN-MEM-04 stays green). (L4-KG-013)
- [x] 3.4 The commit: `git add` the changed lessons paths, then `git commit -m "chore(memory): lesson <id> promoted [skip ci]" -m "Promoted-from: <inbox path>"` with the person's identity and no `L4-*` trailer. Then delete the proposal and its `.evidence.md`. With `--no-commit`: write, keep the proposal, and print the two git lines. Test: SCN-KG-27, whose last step calls `inject_for_task` on a task path under the scope and gets the id. (L4-KG-013)
- [x] 3.5 `run_lessons` accepts `promote ID` with `from_dir`, `yes` and `no_commit` keyword options. `list` and `lint` stay byte-for-byte (their existing tests stay unchanged). (L4-KG-013, L4-KG-014)

## 4. Extraction and blame (wave 2, agent D: `kg/extract.py`, `kg/blame.py`, `tests/unit/kg/test_extract.py`, `test_blame.py`)

- [x] 4.1 Ledger edges: `HAS_RUN`, `USED_PROFILE{role}` (`availability.selected`), `INJECTED{task, role}` (`prompt.rendered{task, lessons}`, the role from the event), `ATTEMPT_FAILED{task, phase, attempt}` (class from 1.4), `ASKED{kind, answered_by}`, `STOPPED{phase, detail}` (`phase.changed` into `halted`/`escalated`), `RETRIED`, `RESTARTED`, with `src = <sha10>:<path>#<seq>`. (L4-KG-005)
- [x] 4.2 `verdict.json` edges: `HAS_ROUND`, `VERDICT`, `RAISED{severity, source, spec_gap}`, `ABOUT`, `IN_CAPABILITY` (OpenSpec: the first part of the alias; Kiro: the unit), `KEYED`, `GATE_FAILED`, with JSON-pointer `src`. The changed files of a round only when both shas are local, else `files_unknown`. Test: SCN-KG-10 resolves every `src` with `git cat-file`. (L4-KG-005)
- [x] 4.3 The lesson link by dedupe key only (`LESSON_RULES[key].finding_title` → its recurrence key; `kg-*` → its pattern). The `Source` line is never parsed. Test: SCN-KG-11. (L4-KG-005)
- [x] 4.4 `blame.classify` as one pure function with D6's table, first match wins. A table-driven test with one row per rule plus `unknown`. Tests: SCN-KG-14, SCN-KG-15. (L4-KG-007)
- [x] 4.5 Redaction: every text field through `app.redactor.redact_text`, then `scrub_for_commit`, before it enters a node or an edge. Test: SCN-KG-22 (the index part). (L4-KG-011)

## 5. Report, why, propose (wave 3, agent E: `kg/report.py`, `kg/why.py`, `kg/propose.py`, `tests/unit/kg/test_report.py`, `test_why.py`, `test_propose.py`, `tests/unit/kg/snapshots/`)

- [x] 5.1 The report sections of D8, in order, with `n = ` on every numbered line, `none (n = 0)` for an empty section, `approximate` in the header of each key-based section, and sorting by count then key. Tests: SCN-KG-18 (snapshot), SCN-KG-12, SCN-KG-13. (L4-KG-006, L4-KG-009)
- [x] 5.2 Lesson outcomes (D7): injections by units, tasks and prompts; the attempt failures of the same run and task after the injection's `seq`; the later-round findings with the linked key; the three statuses. Tests: SCN-KG-16 (fixture from the events of job 5528), SCN-KG-17. (L4-KG-008)
- [x] 5.3 Profiles by role and stops by code, as D8 items 7 and 8. Snapshot test. (L4-KG-009)
- [x] 5.4 `why`: the unit timeline (D9) and the 1-hop view for `F-`, `L-`, `r-` and `<unit>#Q-`. Tests: SCN-KG-20, SCN-KG-21. (L4-KG-010)
- [x] 5.5 `propose` (D10): the patterns (a), (b) and (c), at least N units; skipped when a lesson or a `LESSON_RULES` rule covers them; the draft and the evidence file; only harness-owned strings; the `TODO(person):` line; `--dry-run`; and the ignore warning from `git check-ignore`. Tests: SCN-KG-24, SCN-KG-25, SCN-KG-26, SCN-KG-22 (the proposal part). (L4-KG-012)

## 6. Commands and boundaries (wave 3, agent F: `kg/cli.py`, `src/l4/commands.py`, `src/l4/cli.py`, `tests/unit/cli/test_dispatch.py` (rows only), `tests/unit/kg/test_cli.py`, `tests/unit/kg/test_boundaries.py`)

- [x] 6.1 Handlers `run_kg_build`, `run_kg_report(out, min_units)`, `run_kg_why(id)`, `run_kg_propose(min_units, dry_run)`. Each builds the index first when `read_index` says `missing`, `incomplete` or `stale`, and prints `index rebuilt (…)`. Exit codes 0, 2 and 1 as in L4-KG-002. `--out` inside the repository must be git-ignored. Tests: SCN-KG-19, SCN-KG-23. (L4-KG-002, L4-KG-009, L4-KG-011)
- [x] 6.2 `commands.py`: `"kg build"`, `"kg report"`, `"kg why"`, `"kg propose"` → `l4.kg.cli:*`, owning change `experience-graph`. `cli.py`: the `kg` group (as `feedback`), the options, and the `lessons` options `--from`, `--yes`, `--no-commit`. `test_dispatch.py`: the four `kg` names in `SECTION_2_1` and their `ARGV` rows. No other test line changes. (L4-KG-014)
- [x] 6.3 `test_boundaries.py`. Static: an AST scan of `src/l4/**` finds no import of `l4.kg` outside `src/l4/kg/`, no import of `l4.memory.promote` or `l4.memory.inbox` outside `l4.memory.cli`, and no import from `kg/` of `l4.agents`, `l4.llm`, `l4.s1`, `l4.forge`, `l4.sandbox`, `l4.availability`, `l4.vcs.refresh`, `l4.vcs.push`, `socket`, `urllib`, `http`. Dynamic: the subprocess import check of SCN-KG-01. Behaviour: SCN-KG-02 with `socket.socket` patched to raise and the recording `Git`. (L4-KG-001)
- [ ] 6.4 End-to-end with `CliRunner` on the fixture: `l4 kg build`, `report`, `why`, `propose`, then `l4 lessons promote` on an edited draft. Assert that `git status --porcelain` shows only the inbox files before the promote and only the commit after it. (L4-KG-001, L4-KG-013)

## 7. Docs and SPEC (wave 4; 7.1 lands in the same commit as 6.2, because `tests/unit/test_spec_commands.py` needs a SPEC 2.1 row for every handler)

- [x] 7.1 SPEC:
  - four rows in 2.1 (`l4 kg build`, `l4 kg report [--out PATH] [--min-units N]`, `l4 kg why ID`, `l4 kg propose [--min-units N] [--dry-run]`), each with its side effects (cache-root index; inbox files);
  - the `l4 lessons [list|lint|promote ID]` row gets `[--from DIR] [--yes] [--no-commit]`;
  - a new §13.1 "Experience graph (manual)" with L4-KG-001..014;
  - L4-MEM-002 names L4-KG-013 for `promote`;
  - SCN-KG-01..30 in a new §23.x;
  - delivery row 20 `experience-graph`.

  `python3 scripts/check_spec.py docs/SPEC.md` reports nothing uncovered or undefined.
- [x] 7.2 `docs/runbook.md`: a section "Reading the history (`l4 kg`)", with what each command reads, where the index lives, how to fetch the attempts refs, how to promote a draft, and the rule that a report from a client repository never goes into the harness's `docs/live/`, and one from a test repository only after `scripts/dev/scrub.py check`. ASD-STE100.
- [x] 7.3 README: the feature state (manual, report only, n is small today). `openspec/changes/memory-lessons/tasks.md` 3.8 is marked done with a pointer to this change.

## 8. Review and live validation

- [ ] 8.1 An independent review of the whole change on the session model, against L4-KG-001..014 and the D1 boundary. Fix every confirmed finding.
- [ ] 8.2 The full suite is green on the CI shards, with no existing assertion changed (L4-KG-014, SCN-KG-30).
- [ ] 8.3 Live, by hand, on a local clone of a test repository's history (the GitLab and GitHub dummy repositories), with the attempts refs fetched: `l4 kg build`, `l4 kg report --out .l4-out/kg/report.md`, `l4 kg why` for one restarted unit. Check five numbers of the report against `git show` of their `src`. After `scripts/dev/scrub.py check` is clean, save the evidence in `docs/live/experience-graph/`. (L4-KG-004, L4-KG-005, L4-KG-009)
- [ ] 8.4 If a failure class recurs in at least 2 units: `l4 kg propose`, a person writes the advice, then `l4 lessons promote` on the base branch. Record the commit, and in later units record the `lessons.injected` events and the lesson's line in `kg report`. If nothing recurs, record `no pattern at n = <units>` and stop. This is the success criterion of design "How the implementer benefits". (L4-KG-008, L4-KG-012, L4-KG-013)
