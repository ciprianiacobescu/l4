Every task follows these rules:
- Read `proposal.md`, `design.md` and `specs/gitlab-adoption/spec.md` of this change first. Every text, field,
  signature and version is in `design.md` (D1 to D5 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree, with its own `.venv` (`uv sync --inexact`). Never change git configuration.
  Never push. No network: the setup tests use the fake API of `tests/unit/setup/`.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `gitlab-adoption <n.m>: …`, with
  no trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer". No hostnames, project names or tokens in docs or fixtures.
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/ci/test_gitlab_jobs.py` (`parse_gitlab_ci`); `tests/unit/setup/test_gitlab_setup.py` and
`test_gitlab_setup_flow.py` (the fake GitLab API, rows); `tests/unit/doctor/test_checks_ci.py` (CI-005/CI-006 as the
model); `tests/unit/init/test_ciedit.py` and `test_init_cli.py`.

## 1. The evaluator (D1; L4-INS-007)

- [x] 1.1 `src/l4/ci/gitlab_rules.py`: `Pipeline`, `job_decision`, `workflow_decision`, `jobs_on`, `JobsOn` (with `normal_run` and `normal_unknown`, D3), the
  expression parser and the `only`/`except` rules of D1. Expose from `parse_gitlab_ci`'s result what `jobs_on` needs
  (the merged raw keys per job and the top-level `workflow`), without changing what it returns today. Tests (new
  `tests/unit/ci/test_gitlab_rules.py`): each operator, precedence, three-valued logic, `when: never`/`manual`, `changes`
  and `exists` unknown, every `only` keyword, a branch name and a `/re/`, the default `only`, `except`, `workflow`,
  an unreadable expression unknown, hidden and trigger jobs and `l4` left out.

## 2. Setup and doctor (D2, D3; L4-INS-007, L4-INS-008)

- [x] 2.1 Setup's row (D2) and the two warnings (D3) for schedule and api. Tests for SCN-INS-18, SCN-INS-19, SCN-INS-20
  (setup part), SCN-INS-22 (setup part) in the setup tests; update tests that pin the old row text.
- [x] 2.2 Doctor `CI-007` (D3). Tests for SCN-INS-20, SCN-INS-21, SCN-INS-22, SCN-INS-29, the push pipeline of a unit branch and the skip cases in `test_checks_ci.py`;
  add `CI-007` wherever the doctor's check list is pinned (registry tests, docs table of checks).

## 3. The anchor job (D4; L4-INS-009)

- [x] 3.1 `ciedit.py`/`init.py`: the append of D4 after the include edit, the stage rule, the tags line, line endings,
  `_parses_back`, the report line. Tests for SCN-INS-23, SCN-INS-24, SCN-INS-25, a CRLF file, an existing
  `l4-pipeline-anchor`, and a created file unchanged.

## 4. The bot's level (D5; L4-INS-010)

- [x] 4.1 `SetupOptions.merge_policy` (wired from the config where `base_branch` is), `needed_level()` with the
  protected-branch read (exact name and wildcard), the creation level, the `INFO` and `WARN` rows, `--dry-run`. Tests
  for SCN-INS-26, SCN-INS-27, SCN-INS-28 and the "no one" row.

## 5. Docs

- [ ] 5.1 `docs/SPEC.md`: L4-INS-007 to L4-INS-010 after L4-INS-006 and SCN-INS-18 to SCN-INS-29 after SCN-INS-17, the
  doctor table row for `CI-007` where the other CI checks are listed, and change row 65 `gitlab-adoption` (after row
  64, which another branch adds: put yours as 65 and leave 64 out). `check_spec.py` clean.
- [ ] 5.2 `docs/runbook.md`, GitLab setup section: the empty-pipeline rule and the anchor job, the setup row, and the
  bot level (when setup makes a Maintainer token and how to rotate a Developer one).
