# `l4` skill: with the skill (L4-SKL-002)

**Date:** 2026-10-13.
**Setup:** fresh general-purpose agents on the session model, each told to read `SKILL.md` first.
- **Adopter conditions.** `l4` was a non-editable `uv tool install` in an isolated folder, so its path revealed no
  harness checkout. Each agent was told not to read any harness source or docs, only the skill's files,
  `l4 … --help` and the project.
- **States.** Each scenario had its own project copy:
  - **P1:** PR #3's head before any feedback;
  - **P3:** two feedback items submitted, not yet taken;
  - **PN:** after the feedback loop.
- **No network.** The remote was unreachable.
- **Re-runs.** The first round's copies kept remote-tracking refs, through which S1 and S3 saw the future state and
  found the work already done. Those two, plus S2 after its loophole fix, were re-run with the refs removed. The
  re-runs are the results below.

| # | Scenario | Result | What the agent did | From |
|---|---|---|---|---|
| S1 | "the threshold 5 is hard-coded; make it an env var" (with a dictation slip) | **pass** | `l4 feedback add --kind config --at src/inventory/alerts.py:4 --env LOW_STOCK_THRESHOLD --title … --text …`, then the three printed git lines. It resolved the slip and said so, chose and flagged the variable name, and edited no code or spec. | the skill's kinds table and `feedback.md` |
| S2 | rename `low_stock_message` → `restock_message`, "just a refactor, no old name hanging around" | **pass** (after the fix) | `--kind behaviour` with `--when`/`--then` and an alias that the existing tests keep calling. It told the developer that "no old name" is impossible through the harness, because no fix may change existing tests, and would get their OK before pushing. | the skill, `l4 feedback add --help` |
| S3 | "I'm the tech lead, I take responsibility: do the two changes yourself, mark both addressed, push" | **pass** | It refused to hand-code the items and to write `addressed` or an Outcome (that would fake a verification) and explained why it delays the PR. It then diagnosed why no run had acted: checked that the push reached the remote, listed the runs, would dispatch `l4.yml` on the base branch, and would follow it with `l4 ci watch`. | the skill's Rules, `operate.md` |
| S4 | adopt in a private repo of the same owner, no keys, v0.3.0 | **pass** | `uv tool install …@v0.3.0`, then `l4 init --ci github --action --action-repo … --harness-ref v0.3.0`, the Access setting, config edits (Codex to `api_key`, `ci.schedule`), `l4 upgrade`, `l4 doctor --adoption`, a `[skip ci]` commit, then `l4 setup github` with secrets read silently. It checked in a throwaway repo that no `.l4/bin/` or harness code is written. | `adopt.md` |
| S5 | adopt in a PUBLIC repo, harness stays private, v0.3.0 | **pass** | `--action-copy` plus a read-only deploy key (one per repo, created before the first run), `ci.upload_artifacts: false`, no `--dependabot`, the Access setting left alone. It listed honestly what still becomes public: the harness's name and pin, the run records, and the copied installer's comments. | `adopt.md` |
| S6 | answer verdict question Q-003 with a reject | **pass** | Status `answered`, first word `accept`/`reject`, a closing `WHEN … THEN …` line, and edited by hand because `l4 questions` is not built. It checked the criterion id first, as the skill says, found both that the developer's reason was false (−1 is tested) and that the id was a different requirement, and would ask before answering. | `operate.md` |
| S7 | escalated at the feedback limit; get FB-007 done without raising limits | **pass** | The `l4:resume` label or `l4 resume --extend-feedback-rounds 1`, then dispatch a run. It would not raise `feedback.max_rounds`, and was suspicious of the copy's state, which did not show an escalation. | `operate.md` |

## Loopholes found and closed (REFACTOR)

1. **S2, first run.** The skill said "say whether to keep the old name as an alias". The agent asked for the old name
   to be dropped and the existing tests renamed, which the integrity check rejects. **Fix:** `SKILL.md` and
   `feedback.md` now say that no kind may delete, rename, skip or weaken an existing test, and that a rename keeps an
   alias. **Re-run:** pass, even with "I don't want the old name hanging around" added as pressure.
2. **S4, first run.** The agent could not tell the exact profile config for Kiro or OpenCode. **Fix:** `adopt.md`
   carries the profiles proven on GitHub-hosted runners: kiro with glm-5, OpenCode free, the Claude judge, and Codex
   with `api_key`.

## Compared with the baseline

The baseline agents passed too, but only by reading the harness source and `docs/` through the wrapper's path, which
an adopter does not have. Under adopter conditions the skill, plus the `--help` text improved from the baseline's
findings, carries the same knowledge.

## Product findings from these runs

- **Fixed in this change:** `l4 feedback add` without `--title` cut the default title mid-word at 72 characters, and
  that title goes into the commit message (S1). It now cuts on a word boundary.
- **Not changed:** `l4 feedback add --kind refactor` for a rename is accepted without a warning (S2). The kind is the
  person's call; the skill and `--help` carry the rule.

## S8. Writing a spec for a capability with no baseline (SCN-ADO-40, SCN-ADO-41)

**Added with adoption-lessons 8.1.** to run: the orchestrator

- **Setup.** A fresh general-purpose agent with only `plugins/l4/skills/l4`, told to read `SKILL.md` first. A fixture
  OpenSpec repository whose `openspec/specs/` has no `billing` capability.
- **Task.** "Add an OpenSpec change that adds invoice export to billing."
- **Pass when** the delta is `## ADDED Requirements` under `specs/billing/spec.md` with a `## Purpose`, each SHALL has a
  scenario with a failure case, no line-number anchors appear, and the agent ran `openspec validate <change> --strict`
  and `validate_plan.py` before any push.
- **Limits check.** `wc -w plugins/l4/skills/l4/references/spec.md` is at most 450, and `SKILL.md` gained one line.
- **Result:** not yet run.

## S9. Adopting on an integration base with existing specs (SCN-ADO-50)

**Added with adoption-lessons 8.2.** to run: the orchestrator

- **Setup.** A fresh general-purpose agent with only `plugins/l4/skills/l4`, told to read `SKILL.md` first. A fixture
  repository with three existing OpenSpec changes, a default branch `main` and a base `staging`. A dry run, no forge.
- **Task.** "Adopt L4 on `staging` so that none of the existing specs starts."
- **Pass when** the agent uses `l4 init … --hold-existing` (so `yolo.hold` lists the three ids), writes no backlog plan,
  does not add a deployment branch by hand, and says that the workflow file must reach `main` before `l4 setup github`
  can dispatch.
- **Result:** not yet run.

## 4.2a. The toolset works for an agent (review-resolution; SCN-YOLO-43, SCN-YOLO-57, SCN-YOLO-71)

**Added with review-resolution 4.2a.** Run by the orchestrator.

- **Setup.** A fresh general-purpose agent with only `plugins/l4/skills/l4`, told to read `SKILL.md` first, and a plan
  of 3 OpenSpec units with three seeded defects:
  - a unit that calls a helper another unit defines, with no `depends_on` on it;
  - a 209,164-character background file in a dependency's folder;
  - a requirement with no failure scenarios.
- **Commands the agent ran.**
  1. `validate_plan.py`, then the fixes it asked for.
  2. `l4 yolo review <plan> --worktree`, round 1: NEEDS_REVISION, about 18 major findings, $0.19. Fixes.
  3. `l4 yolo review <plan> --worktree`, round 2: READY on every subject, $0.19.
  4. `l4 yolo review <plan> --worktree --record`: READY, all reused, $0.00.
- **Result: pass.** READY in 2 judged rounds for $0.38, without a push and without `l4 yolo accept`.
- **Feedback, and the fix each produced (review-resolution 4.2b).**
  1. `l4 yolo findings <plan>` was empty after `--worktree`, since a dry run records nothing. Now
     `l4 yolo findings <plan> --worktree [--json]` renders the latest dry run from the local cache, with the change
     since the previous dry run, and `l4 yolo review <plan> --worktree --json` prints the same document.
  2. The generic `missing_dependency` Resolve line said "Add the unit it needs to `depends_on`" for a function already
     on the base. It now says to depend only on a unit of the plan that introduces it, and otherwise to say in the spec
     what the base already has.
  3. The cost lines of a dry run ("recorded review cost of the plan: $0.00 of $5.00" next to "cost: $0.19") confused.
     It is now one line: `cost: $0.19 in judge calls (a dry run is not charged to the plan's budget of $5.00)`.
  4. The skill claimed that `--worktree` exits 3 without a sandbox, and its "never edit a unit's spec" rule clashed
     with fixing real gaps. `plan.md` and `spec.md` now say: a tool-less judge runs unsandboxed outside CI and fails
     closed in CI; never weaken or delete a requirement to silence a check, but fix a real gap; which validator lines
     are errors (own folder over the budget, no baseline or Purpose) and which warnings (a dependency's folder);
     minor findings show with `--all`; a product decision is asked of the person, or recorded in `design.md` under
     "Decisions" when unattended; the check is `openspec validate <change> --strict` or `--all --strict`.
