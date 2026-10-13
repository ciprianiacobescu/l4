# `l4` skill: baseline (agents without the skill)

**Date:** 2026-10-13.
**Setup:** each scenario ran in a fresh general-purpose agent on the session model, with no `l4` skill.
- **Working directory:** a copy of a consumer repository that uses L4: the dummy `l4-dummy-action` on the unit branch
  of PR #3, a Kiro unit whose two feedback items were already addressed.
- **Tools:** `l4` on PATH through a wrapper script.
- **Instructions:** read anything, run read-only commands, change nothing, and report the exact commands and edits it
  would make.

**Caveat on the setup.** The wrapper's path revealed the harness checkout, and every agent read the harness source and
`docs/` from there. A real adopter with the setup action has only `l4 --help` and the files in their repository, so
these baselines measure a better-informed agent than the real one. The S1 and S3 setups were also flawed: the copied
unit already had the requested change addressed. The with-skill runs use the same setup, so the two are comparable.

| # | Scenario (D8) | Outcome | Where the knowledge came from | Gap it showed |
|---|---|---|---|---|
| S1 | "the threshold is hard-coded; make it an env var" (with a dictation slip) | **pass**: found FB-002 already addressed, would not file a duplicate, and named `l4 feedback add --kind config --env …` correctly | `l4 feedback --help`, `feedback.md` header | none |
| S2 | "rename `low_stock_message` to `restock_message`, behaviour unchanged" | **pass**: `--kind behaviour` with WHEN/THEN, keeping an alias for the existing tests | `docs/feedback.md` (harness checkout) and `_freeze_refactor` in the source | **`l4 feedback add --help` accepts `--kind refactor` for a rename without a word.** An adopter without the harness docs would send it as refactor and burn rounds. |
| S3 | "edit `feedback.md`, set both items addressed, commit and push" | **pass (refused)**: explained that the harness owns those fields and that a push after the hand-off sends the unit back to work | harness source (`review.py`, lifecycle) | none, but only because the items were already addressed (setup flaw) |
| S4 | "adopt L4 in my private repo, no keys, release v0.3.0" | **pass**: the action form (`l4 init --ci github --action --harness-ref v0.3.0`), the Access setting, `l4 setup github` | `docs/quickstart.md`, init/upgrade/setup source | `init --action` writes a config that cannot run on GitHub-hosted runners: `runner_tags` → self-hosted, a Codex subscription implementer, an `L4_FORGE_TOKEN` forge token. The fixed `*/30` schedule costs about 1,400 runner-minutes a month on a private repository, and `l4 upgrade` overwrites hand edits. `l4 init --dry-run` is not implemented. |
| S5 | "adopt L4 in my PUBLIC repo, harness stays private" | **pass**: `--action-copy` plus a read-only deploy key (one per consumer), `l4 setup github --secret L4_HARNESS_SSH_KEY=…` | quickstart, the live spike evidence, init source | Every run uploads `l4-out` (prompts, transcripts), publicly downloadable on a public repository, with no setting. Copy mode: `l4 upgrade` never refreshes `.github/actions/l4/action.yml`. `--action-copy` needs a git checkout of the harness, not an installed `l4`. `--dependabot` cannot move a copy-mode pin (`commit:` input). |
| S6 | "answer verdict question Q-003 with a reject" | **pass**: Status `answered` (not `accepted`), first word `reject`, a `WHEN … THEN …` regression line; checked the criterion id first; knew `l4 questions answer` is a stub | harness source (`verdicts.py`), SPEC | none |
| S7 | "escalated at the feedback limit; get FB-007 done without raising limits" | **pass**: the `l4:resume` label (one feedback round, by a member) or `l4 resume --extend-feedback-rounds N`, then dispatch a run | harness source (`resume.py`, `sweeper.py`) | **Bug:** the PR note's halted section says `--extend-fix-rounds` and "one more fix round per label event" for a feedback-limit escalation, which `l4 resume` refuses (`ci/resume_label.py` `halted_section`). |

## What the skill must carry, given these baselines

An adopter's agent cannot read the harness source or `docs/`. Everything the baselines learned there has to be in the
skill or in the shipped `--help`:
- **Choosing the feedback kind.** A rename, or any change that needs test edits, is `behaviour`, not `refactor`
  (refactor freezes the tests).
- **Harness-owned fields.** Never set `addressed`/`taken` or write the Outcome; never push spec edits to hurry a PR.
- **Questions.** Verdict answers: Status `answered`, first word `accept`/`reject`, `WHEN … THEN …` for a regression;
  `l4 questions` is not built yet, so the file is edited by hand.
- **Resume.** For a feedback-limit stop: the label gives one feedback round; `l4 resume --extend-feedback-rounds N`;
  then dispatch a run.
- **Adoption.**
  - A private repository of the same owner: `--action`, no key, the Access setting.
  - A public repository: `--action-copy` plus a read-only deploy key.
  - In both cases, a hosted-runner config, then `l4 setup github`.

## Product fixes the baselines call for (done in this change, before the with-skill runs)

1. `l4 feedback add --help` names the rename/test-change case.
2. The halted note's wording for a feedback-limit escalation.
3. Hosted-ready defaults from `l4 init --ci github --action`.
4. `ci.schedule` in the config.
5. `ci.upload_artifacts` in the config.
6. Copy mode: the action ships in the package, works from an installed `l4`, and is refreshed by `l4 upgrade`.
7. `--dependabot` refused with `--action-copy`.
