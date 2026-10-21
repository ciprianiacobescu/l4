# Human feedback, live on a Kiro unit (L4-FBK-013)

**Date:** 2026-10-13.
**Repository:** `ciprianiacobescu/l4-dummy-action` (private), GitHub-hosted `ubuntu-24.04`.
**Harness:** the setup action at the commit of `integration/feedback-action`, which holds the `human-feedback` and
`adoption-kit` changes.
**Agents:**
- implementer: kiro-cli 2.30.0 with `KIRO_API_KEY`, model `glm-5` (vendor zhipu);
- judge: Claude Code with a subscription token, serving `claude-sonnet-5-5`.

Both credentials are secrets of the environment `l4`.

Labels: **[V]** observed in the logs and files of this folder.

## The loop

1. **Kiro writes the spec** [V]. On the maintainer's Mac, `kiro-cli chat --no-interactive --v3 --mode spec` ran in an
   empty HOME with only `KIRO_API_KEY`. In 55 s it wrote `.kiro/specs/add-low-stock-message/` (requirements, design,
   tasks, wave graph). The brief and the files as written are in `authoring/`.
2. **Kiro implements it; Claude judges** [V, run 38328650333, harness `5e83ea81`]:
   - Task 1.1's first red attempt was rejected as vacuous (its tests passed against zero-value stubs), and the retry
     passed red, then green.
   - Task 2.1 was confirmed already satisfied by 1.1's code.
   - The judge gave `verdict PASS (round 1, 4/4 criteria pass)`, and PR #3 was marked ready. Kiro hard-coded the
     threshold `5` (`files/alerts.py.before`).
3. **A person asks for two changes** [V] with `l4 feedback add` on the unit branch, then commit and push
   (`files/feedback.md.as-sent`):
   - FB-001 `refactor`, `--at src/inventory/alerts.py:2-3`: move the validation into `_require_non_negative`.
   - FB-002 `config`, `--at src/inventory/alerts.py:4 --env LOW_STOCK_THRESHOLD`: read the threshold from the
     environment, default 5.
4. **First try: the run stopped before the harness** [V, run 38329266005]:
   - The workflow's `base checkout` step fetched the base branch without credentials (`persist-credentials: false`).
     In a private repository that fails: `fatal: could not read Username for 'https://github.com'`.
   - The step only ever worked on the public github-parity dummy.
   - **Fix:** the step now detaches to `origin/<base>`, which `fetch-depth: 0` already fetched.
   - `l4 upgrade` now re-renders the whole workflow, so the fix reaches existing adopters. The dummy was upgraded with
     it (harness `19a2403a`).
5. **The feedback loop** [V, run 38330251183, 314 s, one job]:
   - `phase in_review → implementing (spec_edit_after_handoff: 1 commit, … feedback(add-low-stock-message): FB-001 … by CiprianSpot)`
   - `verdict FAIL (round 2, …, 2 finding(s))`: the two items were taken at step 0, with no gates and no judge.
   - `fix unit 1` was written as a **Kiro bugfix spec** (`files/fix-1.bugfix.md`). It holds the person's requests
     first, with the quoted code, the built criterion `2.1 WHEN the environment variable LOW_STOCK_THRESHOLD is set …`,
     the unchanged sentence, and `3.1 WHEN LOW_STOCK_THRESHOLD is not set THEN the system SHALL CONTINUE TO behave as
     before this change`.
   - `task 1.1 [chore] Feedback FB-001 (refactor)`: Kiro took 51 s, and the gates passed with the tests unchanged.
   - `task 1.2 Feedback FB-002 (config)`: red `2 new test(s) failing as expected`, then green `all tests passing`.
   - `verdict PASS (round 3, 6/6 criteria pass)`: the judge answered both items addressed with evidence. Both read
     `addressed` with their Outcome in `feedback.md` (`files/feedback.md.after`), and `verification.md` lists them
     under `## Feedback` (`files/verification.md.round3`).
   - The unit handed off again: `PR #3 marked ready for review`.
6. **The result** (`files/alerts.py.after`): a `_require_non_negative` helper, and `_get_threshold()` reading
   `LOW_STOCK_THRESHOLD` with the default `5`.

   The PR's sticky note (by `github-actions[bot]`) reads:
   ```
   ### Your feedback

   - FB-001 refactor src/inventory/alerts.py:2-3 — addressed in round 3 at 0a0be6d7f3
   - FB-002 config src/inventory/alerts.py:4 — addressed in round 3 at 0a0be6d7f3

   To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE --text "…", then commit and push (docs/feedback.md).
   ```

## Also seen

- **The CLI cache key now covers the config's agent CLIs.** The run restored no cache, because the key was new once
  kiro-cli joined. Doctor installed OpenSpec, Claude Code and kiro-cli, and the job saved the cache. Before that fix a
  cache hit without kiro-cli was never re-saved (run 38328650333: `provision: installing kiro-cli` on a hit).
- **No secret value** of `KIRO_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` is in any file of this folder. This was checked
  against the Mintkey values; the logs show the variables only as `***`.

## Open

- **A person merges PR #3.** The harness never merges (L4-ARC-003). After the merge, the next base run records the
  Kiro done-gate.
