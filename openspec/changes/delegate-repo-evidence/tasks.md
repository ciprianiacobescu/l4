## 1. The repository's own `.l4/` files are evidence (L4-DLG-005)

- [x] 1.1 Tests first, in `tests/unit/delegate/test_reply.py` (helpers `check`, `reply`, `cite`; add the files the
  tests need to the fixture repository the file's tests use, read how it is built first):
  - `test_a_repository_gate_script_is_evidence` (SCN-DLG-120): `.l4/gates/test.sh:2` and `.l4/config.yaml:1` with
    quotes at those lines → `Kept`; `spec:` is not involved.
  - `test_the_harness_l4_files_stay_harness_written` (SCN-DLG-121): `openspec/changes/<unit>/.l4/ledger/r-1.jsonl:1`,
    `.l4/vendor/x.py:1`, `.l4/ci/l4.gitlab-ci.yml:1`, `.l4/bin/l4:1`, `.l4-out/junit.xml:1`, `questions.md` and
    `verification.md` → `Discarded` with exactly `checked <ref> cites a harness-written file (questions.md,
    verification.md, the harness's .l4/ files): not evidence`, not retryable.
  - Update every existing assertion of the old reason text (`grep -rn "harness-written file" tests/`) to the new one.
  Then change `_harness_written` and the reason in `src/l4/delegate/reply.py` as design D1 and D2 (a module constant
  `HARNESS_ROOT_DIRS`, a constant for the reason text). Run `tests/unit/delegate`.
  - Result: done. Red on the unchanged code (9 failed in `test_reply`, 1 in `test_pass`): the two new tests, `test_a_repository_gate_script_is_evidence` (`assert isinstance(check(...), Kept)` for `.l4/gates/test.sh:2`, `Discarded(reason='checked .l4/gates/test.sh:2 cites a harness-written file (questions.md, verification.md, .l4/): not evidence')`) and `test_the_harness_l4_files_stay_harness_written` (the new reason text), and the existing tests whose assertion of the old reason text was updated (`test_harness_written_files_and_one_character_quotes_do_not_resolve`, `test_a_harness_written_ref_is_named_as_such` x6, and `test_a_reply_citing_a_harness_file_is_discarded_with_that_reason` in `test_pass.py`, checked red alone on the unchanged `reply.py`). Guards that pass before and after: every other test of `test_reply`, including the `questions.md`, `verification.md`, unit-ledger and `src/pkg/.l4/` cases of the old tests (they stay harness-written). Two test inputs changed with the rule: `.l4/ledger.jsonl:1` of `test_a_harness_written_ref_is_named_as_such` (a file in the repository's root `.l4/` is now the repository's own) became `.l4/vendor/ledger.jsonl:1`. Implemented: `HARNESS_ROOT_DIRS` and `HARNESS_REASON` and the four-part `_harness_written` of design D1 in `reply.py`. One addition beyond D1: `_harness_ref` also reads a `spec:` name as the path it has in the unit folder (`HeadTree.unit_rel`), so `spec:.l4/ledger/r-1.jsonl` (the unit's ledger, which an existing test names) keeps the harness-written reason instead of becoming "does not resolve" and being asked again.
- [x] 1.2 Tests first, in `tests/unit/delegate/test_prompt.py`: the version is `delegate@5` (update the assertion and
  the module docstrings that say `delegate@4`, in the test and in `src/l4/delegate/prompt.py`); the system text names
  `.l4/config.yaml`, `.l4/gates/` and `.l4/plans/` as evidence and `.l4-out/` and a unit folder's `.l4/` as not. Then
  the prompt text of design D2, `PROMPT_VERSION = 5`, and `uv run python -m l4.templatelock --write`. Run
  `tests/unit/delegate`, `tests/unit/test_template_lock.py` and
  `tests/unit/verifier/test_testwriter_names.py::test_the_lock_is_regenerated`.
  - Result: done. Red on the unchanged code: `test_the_version_and_the_digest` (`assert PROMPT_VERSION == 5`) and `test_the_prompt_states_which_files_are_no_evidence` (rewritten for the new sentence; the old assertions of `anything under `.l4/`` removed). Guards that pass before and after: the other tests of `test_prompt` and `test_template_lock`. `PROMPT_VERSION = 5`, the sentence of design D2 (and "a reference to a file that is no evidence", since "one of them" would now point at the evidence files too) in `prompt.py`, the module docstring says `delegate@5`, `src/l4/templates.lock.json` regenerated (delegate: version 5, sha256 7231d351...).
- [x] 1.3 Docs:
  - `docs/SPEC.md`, L4-DLG-005: replace "A `checked` entry MUST NOT cite `questions.md`, `verification.md` or a path
    under `.l4/` (the harness's and the asker's own words)" with the rule of the spec delta (the four harness-written
    kinds; the repository's `.l4/config.yaml`, `.l4/gates/`, `.l4/plans/` are repository files), and the reason text
    `checked <ref> cites a harness-written file (questions.md, verification.md, .l4/): not evidence` with the new one.
  - `docs/SPEC.md`, L4-DLG-004 and SCN-DLG-80: `delegate@4` → `delegate@5`, and L4-DLG-004's amendment list gains
    `0.4.35: which .l4/ files are evidence`.
  - `docs/SPEC.md`: after SCN-DLG-119, `#### SCN-DLG-120 (+) A repository's gate script is evidence · L4-DLG-005` and
    `#### SCN-DLG-121 (−) The harness's .l4/ files stay harness-written · L4-DLG-005`, Given/When/Then as the spec
    delta's scenarios.
  - `docs/SPEC.md` change table: row 79 `delegate-repo-evidence` after row 78, in the form of rows 77 and 78 (the cause:
    two right answers citing the repository's gate scripts were discarded as harness-written and stopped a plan).
  - `CHANGELOG.md`, the `## 0.4.35 (unreleased)` section: `### Fixed`: the delegate may cite a repository's own `.l4/`
    files (`config.yaml`, `gates/`, `plans/`); only a unit folder's `.l4/`, `.l4/vendor/`, `.l4/ci/`, `.l4/bin/`,
    `.l4-out/`, `questions.md` and `verification.md` are harness-written (L4-DLG-005, `delegate@5`).
  Run `uv run python scripts/check_spec.py docs/SPEC.md` and `uv run pytest tests/unit/docs -q`.
  - Result: done. L4-DLG-005 (the rule, the reason text, `delegate@5` in the retry sentence), L4-DLG-004 and SCN-DLG-80 (`delegate@5`, the `0.4.35` amendment), SCN-DLG-16a (it quotes the old reason text, now the new one), SCN-DLG-120 and SCN-DLG-121 after SCN-DLG-119, change-table row 79, CHANGELOG `### Fixed` of `## 0.4.35 (unreleased)`. `tests/unit/docs/test_delegate_docs.py` and `test_delegate_0422_docs.py` exclude the scenarios that later changes own (`range(116, 120)`); now `range(116, 122)`, as delegate-citations did. `check_spec.py` exit 0; `tests/unit/docs` and `test_release_notes` pass.
