## Context

The maintainer's three reports are quoted in `proposal.md`. The readiness review (L4-YOLO-004) and its override
(`l4 yolo accept`, L4-YOLO-027, review-resolution design D7) both depend on a model: D7 can only accept a judgement
that exists, is current, is not BLOCKED and has been made on two versions of the text. When the judge cannot run, no
path leads to activation. This change adds a person's override that needs no judgement, makes `--yes` work for a
person and keeps prompts visible, and fixes how an acceptance is reused and explained.

Labels: [V] verified in the code at c1994292, [I] inferred.

## Goals / Non-goals

Goals: activation of a plan whose specs no model reviewed, by a person's audited decision that is bound to the text;
no hidden prompt; an acceptance that stays bound to what the person saw, and says why when it does not hold.

Non-goals:
- The CI review step is unchanged: before the activation CI still tries to review a force-accepted plan on its next
  run. A review that happens does not void the force acceptance (D4); a judge that fails records nothing (R9) and does
  not stop the run [V: `cycle._review` catches `RoleLimit`/`RoleUnavailable`, logs `the review waits` and returns].
  After the activation CI reviews nothing (L4-YOLO-005).
- The verifier is unchanged: a force-accepted unit carries no findings, so the verifier's judge has nothing to answer
  and the `merge: auto` guard (L4-YOLO-028) has nothing open for it.
- `l4 questions` and `l4 lessons promote` keep their confirmation rules.

## D1. The command

```
l4 yolo accept PLAN --all --force --reason TEXT [--yes]
l4 yolo accept PLAN --all --force --withdraw --reason TEXT
```

`SUBJECT` becomes optional on the CLI. The usage rules, checked in this order before anything is read (exit 2):
`--force` without `--all`; `--all` without `--force`; `--all` with a SUBJECT; neither a SUBJECT nor `--all`; an empty
`--reason` or one over 1,000 characters (as today). `--reason` stays required for the withdrawal: the CLI option is
required for every `accept` call and today's withdrawal records the reason [V: `cli.py` `"yolo accept"`,
`plan.acceptance_withdrawn{reason}`] (the decided design wrote the withdrawal without `--reason`; see "Where the code
changed the design").

What it accepts: every subject of the plan, as `_review_view` names them: each unit id of the plan and
`batch:<id>` for each batch with more than one unit. It reads no review to decide and calls no model: it never builds
the judge factory and never calls `review_plan_costed`.

## D2. Who

`l4.actor.actor(environ, stdin_tty)` decides. Anything but `person` is refused before the plan is fetched: an agent
marker (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `AI_AGENT`, `CODEX_SANDBOX`, `L4_RESULT_PATH`) or no terminal on stdin.
`yolo.review.accept_by_agents` does not apply. An MCP caller is an agent: every tool runs the CLI with
`AI_AGENT=l4-mcp` and no terminal (L4-MCP-002) [V: `mcp/tools.py` `call`], and no MCP tool runs `l4 yolo accept`
[V: the `TOOLS` table]; a test keeps it so. As D7 says, these markers keep honest agents from deciding for a person;
they are not a security boundary.

Refusal (exit 2, nothing fetched or written):
```
accept: --force is a person's decision, never an agent's (<why>), whatever yolo.review.accept_by_agents says
Fix: a person runs, in a terminal: l4 yolo accept <plan> --all --force --reason "..."
```
`<why>` is `<MARKER> is set` (the first marker found) or `stdin is not a terminal`.

Confirmation (D8): the person sees what is overridden, then types the plan id, or passes `--yes`.

## D3. What stays refused

Each keeps its own refusal; nothing is recorded:
1. No plan file on `origin/<base>`, or a file that is not a plan (`_file`, `_valid`: the JSON does not parse or breaks
   the schema).
2. The plan status: before the activation (`new`, `refused`, `admitted`, `reviewed`), or `stopped` with
   `inputs_changed` or `unit_rejected`; the text of `accept.check`'s first rule (factored into
   `accept.status_refusal(state)`, which `check` then calls).
3. The admission of `l4 yolo activate`, exactly: `_read_units(ctx, rev, plan.known_ids(), intake=True)` and
   `admit(plan, known_units=…, cfg=…, held=_held(…), state=…, archived=archived_at(…))`; any finding refuses with
   `accept: <plan> is not admitted:` and one line `  <code>: <text>` per finding (`_findings_text`), as activation
   prints them. Codes as the code has them: `unknown_unit` (a unit no provider finds on the target head: its folder
   does not exist there), `cycle`, `unknown_dependency`, `self_dependency`, `duplicate_id`, `intake`,
   `open_questions`, `held_by_other_plan`, `finished`, `unknown_profile`, `unsupported_profile`, `target_mismatch`,
   `merge_policy`, `empty_plan`, `excluded_and_planned`, `external_dependencies`. Extract the shared code of
   `run_activate` into `_admitted(ctx, rev, plan, plan_id, state, command) -> tuple[_Units, Admission]`.
4. `unit_missing`: a unit whose current digest (`_now_digest`: on its branch when it has one on origin, else on the
   target) is `MISSING` (its folder has no files there):
   ```
   accept: <unit> has no folder with files on its branch or on origin/<base> (unit_missing): nothing can be built from it
   Fix: push its folder, or remove it from .l4/plans/<plan>.json
   ```

The review's harness findings `schema`, `unit_missing` and `completeness` exist only when a review runs
[V: `readiness.blocked`, `review_batches`]; 3 and 4 are their deterministic equivalents. The judge's own
`schema_invalid` (an answer that does not parse) is a model's failure and is overridden.

## D4. The event and the binding

One leased write appends, in order:
- `plan.admitted{plan_digest, order, merge}` unless the state is already `admitted` or `reviewed` at this digest
  with this order (the rule of the CI step [V: `cycle._review`]); the fold then shows `admitted` for a plan no review
  admitted, and the activation adopts the recorded order;
- `plan.force_accepted{plan_digest, subjects, reason, by, actor: "person", marker: null, confirmed}`, where
  `subjects` maps each subject to:
  - a unit: `{"digest": <its current digest>, …}`; a batch: `{"digests": {<unit>: <digest>} of its units, …}`;
  - `skipped`: what an ordinary path would have needed, a list of codes in this order:
    `no_review` (no `plan.reviewed`, or the latest has no entry for the subject), `stale_review` (the latest review's
    `prompt_version` differs from `PROMPT_VERSION`, its `plan_digest` differs from the current one, or a digest of the
    subject differs: a unit's entry `digest`, a batch's units' entries), else from the latest entry: `blocked`
    (BLOCKED), then for NEEDS_REVISION each of `blocking` (a blocking finding whose criterion is not `material`),
    `material` (a `material` finding), `rounds` (`findings.rounds_not_ready(events, subject)` below
    `yolo.review.accept_after_rounds` of the target), and `not_ready` when none of these three applies; READY gives
    `[]`;
  - `review_at`: the `at` of the latest `plan.reviewed` when it has an entry for the subject, else null; `verdict`
    and `material`: that entry's, else null.

`PlanState.force_accepted` is the latest `plan.force_accepted`'s data plus its `at`, in any status but final;
`plan.force_acceptance_withdrawn{reason, by, actor, marker}` sets it to None. A later `plan.force_accepted` replaces
the earlier one as a whole.

Binding, `accept.force_holds(force, plan_digest_now, now) -> dict[str, bool]` (pure): for each subject the event
names, True when `force["plan_digest"] == plan_digest_now` and a unit's recorded digest equals `now[unit]`, or every
`(unit, digest)` of a batch's `digests` equals `now[unit]`; a recorded or current `MISSING` is never equal. `now` is
`_digests(ctx, plan, units)`, the rule activation and `inputs_changed` share. So an edit of the plan file voids every
subject; an edit of a unit's spec voids that unit and every batch that holds it; a tick or a harness file does not
(the digest ignores them). A prerequisite's change voids only the prerequisite's own subject (a deliberate difference
from D7's material key: a force acceptance reviews nothing, so there is no material to bind). Then
`covered = force is not None and every subject of the plan holds`, and a subject is **cleared by force** when it
holds and its recorded `skipped` is not empty (a subject that was READY at its inputs overrode nothing, so a later
judgement of it is not overridden either).

## D5. Activation

`_review_view` computes `force_holds(state.force_accepted, plan_digest(text), now)` first. Every `ReviewView` carries
`force` (one dict per subject whose recorded `skipped` is not empty: `subject, by, actor, reason, holds, skipped`) and
`covered`; `ready` is `covered or (kind == "current" and not problems)`; `forced` is the items of `force` that hold.
In the current case a subject cleared by force is skipped before its verdict is looked at (READY, NEEDS_REVISION and
BLOCKED alike): it is neither a problem nor an ordinary acceptance.

`run_activate`:
- `covered`: the review requirement is skipped (none, stale and problems are not refusals); every other refusal stays
  (status, admission, the rejected unit that did not change, `merge` against `forge.merge_policy`, the target on
  origin, another active plan).
- not covered: today's rules on `view` (which already lets a subject cleared by force through when the review is
  current). When `state.force_accepted` is set and a subject of it no longer holds, the refusal gets the line
  `the force acceptance by <by> no longer holds for <s1>, <s2>: their spec or the plan file changed` and
  `Fix: l4 yolo review <plan>, or a person runs l4 yolo accept <plan> --all --force --reason "..." again`.
- `plan.activated{accepted}` holds, in this order, the ordinary acceptances that hold (agents first, as today) and,
  for each item of `view.forced`, `{"findings": [], "reason", "by", "actor": "person", "force": true}`. When at least
  one force item is there the event also has `review: "force_accepted"`; otherwise the key is absent (the events of
  plans without a force acceptance do not change).
- Output: per force item the line `<subject>: force-accepted without review by <by> (<reason>)`, before the
  `activated on` line.

## D6. Visibility

One text, built by `accept.force_line(subject, by, reason, *, holds=True)`:
`<subject>: force-accepted without review by <by> (<reason>)`, and when it does not hold
`<subject>: force-accepted without review by <by> (<reason>); no longer holds: its spec or the plan file changed`.

- `l4 yolo status` (text): under `review:`, for a plan before the activation or stopped, one line per item of
  `view.force` (indented four spaces), after the problems; the `review:` line ends with
  ` (force-accepted: no review is needed to activate)` when `covered`. For a plan whose activation recorded force items
  (`state.activated_accepted[s].force`), one line per item after `activated by`, indented two spaces. `Next:` is
  `l4 yolo activate <plan> --reason TEXT` when `covered` (before activation). JSON: `review.force_accepted` is null or
  `{by, actor, reason, at, covered, subjects: [{subject, holds, skipped, review_at, verdict}]}` (every subject the
  event names), and `activated_force` is a list of `{subject, by, reason}` (empty when none).
- `l4 yolo findings` (text): when a force acceptance is recorded, after the subjects (or after the `no review yet`
  line, which no longer returns early), one `force_line` per subject with a non-empty `skipped`, in plan order, with
  `holds` from live digests (`run_findings` already reads the units). JSON: the top-level key `force_accepted`, the
  same shape as in status, also in the empty document of a plan with no review.
- `l4 yolo accept --all --force` before the prompt:
  ```
  <plan>: force-accept <n> subject(s) without a readiness review; no model reviews these specifications before they are built:
    <subject>: <words>
  ```
  `<words>` joins, with `, `: `no review`, `a review for other inputs`, `BLOCKED`, `a blocking finding`,
  `a material finding`, `fewer than yolo.review.accept_after_rounds judged versions`, `NEEDS_REVISION`; `[]` is
  `READY at these inputs: nothing is overridden`. After the write:
  `force-accepted: <n> subject(s) of <plan> without review by <by> (person): <reason>` and
  `Next: l4 yolo activate <plan> --reason TEXT`.
- Plan report (`report._accepted_lines`): for the unit's subject and its batch's, an item with `force` gives
  `- <force_line>` (no findings list).
- Carrier and implementer: `cycle._accepted` copies `"force": True` into an item only when the activation's item has
  it (an existing carrier's bytes do not change). `accepted._item` keeps `force: True` when the file has it (absent
  otherwise). `tdd.accepted_block` renders a force item even without findings: the line
  `Accepted without review (<by>): <reason>`; the block then starts with `FORCE_RULE` = "A person accepted the
  specification of this unit without a readiness review: no model checked it before this run. Where the specification
  is silent or unclear, follow the person's reason." (and with `ACCEPTED_RULE` too when an item has findings). Without a
  force item the block is byte for byte today's.
- PR body: `render_pr_body(..., force: tuple[str, str] | None = None)` adds, after the `Verification` line,
  `- Force-accepted without review by <by> (<reason>): no model reviewed this unit's specification before it was built.`
  (`<reason>` on one line). `_pr_body` takes `(by, reason)` from the first force item of `read_accepted(s.ref.path)`.
  The hand-off's `harness_body` check also takes the body rendered without that line, so a PR opened before the force
  acceptance still gets its body refreshed.

## D7. Withdrawal

`l4 yolo accept PLAN --all --force --withdraw --reason TEXT` appends `plan.force_acceptance_withdrawn{reason, by,
actor, marker}` and prints `<plan>: the force acceptance is withdrawn` and `Next: l4 yolo review <plan>`. Never refused
for who runs it (an agent may withdraw: it only makes the activation stricter). Refused as today's withdrawal is: after
the activation (`the acceptances were frozen at its activation …`), and with nothing recorded
(`accept: <plan> has no force acceptance: nothing to withdraw`).

## D8. Confirmation: `--yes` for a person, and no hidden prompt

- `l4 yolo accept PLAN SUBJECT`, `l4 yolo accept PLAN --all --force` and `l4 yolo waive`: a person still sees
  everything the command shows today (the findings, the finding and its acceptance, the D6 summary); then with `--yes`
  no prompt, else the typed plan id. The event records `confirmed: "typed"` or `confirmed: "--yes"`
  (`plan.accepted`, `plan.finding_waived`, `plan.force_accepted`). An agent's `--yes` keeps today's rule (only with
  `yolo.review.accept_by_agents`, recorded `confirmed: "--yes"`); `--force` stays refused for an agent with or without
  it.
- `--yes` for `--force` (the decided design said "no --yes for --force"; a later instruction asked to decide): allowed
  for a person. The person decision rests on the terminal and the absence of a marker; a typed plan id adds no proof
  against a program that drives a terminal, the person typed both `--force` and `--yes`, the summary is still printed
  and the event says `confirmed: "--yes"`. Refusing it would leave the reported hang on exactly the path built for an
  unavailable tool chain.
- A prompt runs only on a terminal: every prompt goes through `_confirm(ctx, plan_id, text, command) -> None` (`command` is the message prefix, `accept` or `waive`, not the actor tuple), which raises
  exit 2 `<command>: no terminal to ask the plan id on: pass --yes` when `_stdin_tty()` is false (defence in depth: today a
  missing terminal already makes the caller an agent [V: `actor`], which never reaches a prompt), and otherwise calls
  `click.prompt(text, default="", show_default=False, err=True)` after `sys.stdout.flush()`. `err=True` writes the
  prompt to stderr, which a pipe on stdout (`| tee`) or a wrapper that holds stdout does not hide [V: click 8.5
  `_readline_prompt` hands the prompt to `input()` with stdout redirected to stderr when `err=True`, and `input()`
  writes and flushes it before it reads; `ctx.say` is `click.echo`, which flushes stdout after each line]. A wrong
  answer exits 2 with nothing recorded, as today.
- The texts: accept `Type the plan id (<plan>) to accept the findings of <subject> as they are`; waive
  `Type the plan id (<plan>) to waive <finding>: the unit merges without it`; force
  `Type the plan id (<plan>) to accept every subject of <plan> without a review`. The CLI help of `--yes` becomes
  `Do not ask for the plan id (a person, or an agent the target lets accept).`

## D9. The acceptance binding: what the code shows, and the fix

Report 3 was checked against each path that records or reuses a judgement [V]:
- (i) "the same material judged twice, the acceptance bound to the older one, a later review reuses the newer one":
  `prior_entries` does keep the newest entry of a material, so this loses the acceptance whenever the ledger holds two
  judgements of one material with different findings. None of the harness's writers makes one in sequence: the CI step,
  `--local` and `--record` all reuse a recorded material (`prior`), `--record --fresh` of recorded material is refused
  (`FreshRefused`), and a CI review that lost its lease to another review is dropped (`_write_review`). It takes two
  reviews that judged the material before either was written (a lost-lease `--local` exits, the CI step drops) or a
  ledger written by another tool. Reproduced synthetically by tasks 3.1.
- (ii) "a `--worktree` dry run's newer judgement is overridden by an older ledger entry at `--record`": `--record` reads
  no local cache and the ledger wins in a dry run (`prior = {**cache, **ledger}`), so the judgement an acceptance is
  bound to (always a ledger entry) is the one reused. This keeps the acceptance; it does not lose it. What a dry run
  with `--fresh SUBJECT` does show is a new judgement of the same material with other findings, and then the text
  `accepted by … (no longer holds: the material changed)`, which is false: the material did not change.
- What a person sees for an acceptance that holds: `l4 yolo findings` prints `<subject>: NEEDS_REVISION` as the
  subject's first line and the acceptance at the end of its block; `review --worktree` prints
  `<subject>: digest …, material …: NEEDS_REVISION (reused)`; `review --local` prints `<subject>: NEEDS_REVISION: …`
  and `Next: l4 yolo findings`; the CI log counts it under `not READY`. None says on that line that the subject is
  accepted and does not stop the activation [I: the likeliest reading of "something accepted still appears as
  NEEDS_REVISION", with the "(reused)" mark read as a stale cache].
- A material that differs between CI and the working tree (a unit with a branch on origin is read there by CI, on the
  working tree by `--worktree`; task marks are part of the material) voids an acceptance on one side only; the text then
  says `the material changed` with no detail.

The fix:
1. `findings.prior_entries(events, prompt_version, accepted=None)`: for a material key that a recorded acceptance is
   bound to (`accepted[s]["material"]`), the entry returned is the newest one with that key whose
   `findings_sha(findings)` equals the acceptance's `findings_sha`, when one exists; otherwise the newest, as today.
   The CI step, `run_review --local` and `run_review_worktree` (ledger part) pass `state.accepted`.
2. `accept.why_not_holds(accepted, entry, review_at) -> str`, one line:
   - entry None: `no entry: the latest review does not judge <subject>`;
   - other material: `other material: accepted on material <m8> with findings <f8>[ judged <t>]; the latest review
     shows material <m8'> with findings <f8'> judged <t'> (<reused|new>); <cause>`, `<cause>` being `its own spec
     changed` when the acceptance's `digests` differ from the entry's (a unit: `{subject: entry.digest}`, a batch: the
     entry's `digests`), else `a prerequisite, its plan entry, its task marks or the review prompt changed`; an
     acceptance without `digests` gets no `; <cause>`;
   - same material, other findings: `other findings of the same material: accepted findings <f8>[ judged <t>]; the
     latest review shows findings <f8'> judged <t'> (<reused|new>)`.
   `<m8>`, `<f8>`: the first 8 characters; `<t>`: the acceptance's `judged_at` (new key of `plan.accepted`: the entry's
   `reused_from`, else the `at` of the review the person accepted; left out for an older acceptance); `<t'>`: the
   entry's `reused_from`, else `review_at`; `reused` when the entry has `reused_from`, else `new`.
   Used by: the status problem line (`(the acceptance by <by> was for <why>)`, replacing
   `(the acceptance by <by> was for other material)`), and `findings.render` (`(no longer holds: it was for <why>)`,
   replacing `(no longer holds: the material changed)`; JSON `accepted.why`, null when it holds). The fix stays the
   existing `accept:` line of `l4 yolo findings` (`accept: l4 yolo accept …` or `accept: not available: …`).
3. Where a verdict is printed, an acceptance that holds is said on the same line: `findings.render`'s subject line
   `<subject>: NEEDS_REVISION (accepted by <by>: it does not stop the activation)`; `review --worktree`
   `…: NEEDS_REVISION (reused), judged <t>; accepted by <by>: it does not stop the activation`; `review --local`
   `  <subject>: NEEDS_REVISION: <first line> (accepted by <by>: it does not stop the activation)` and its `Next:` is
   `l4 yolo activate <plan> --reason TEXT` when every subject is READY or held; the CI log
   `reviewed: <n> READY, <m> not READY (<a> accepted), …` when `<a>` > 0 (the line is unchanged otherwise).
4. Provenance: `findings.render` adds `  reused: judged <reused_from> on the same material` under the subject line of a
   reused entry (JSON `reused_from`); `review --worktree` adds `, judged <t>` after `(reused)`.

## D10. Documentation

- `docs/yolo-mode.md`: a section "When the reviewer is unavailable": the force path and its command, who may run it,
  what it never overrides, the binding, the withdrawal; the risk in its own sentence ("specifications that no model
  reviewed get built: the implementer and the verifier are the only checks"); the alternative first: review in CI with
  `l4 yolo review <plan>` (without `--local`, CI's judge may work where the local one does not); and that CI may still
  review the plan before the activation. "The review" names `--yes` for a person and the why-line.
- `docs/runbook.md`: 12.2a gets "When the judge cannot run" with the commands; the accept text says `--yes`; the
  activation refusals list the force line; 12.2b says a force-accepted unit carries the reason and no findings.
- Skill: `references/plan.md` and `operate.md`: never run `--force` (not even with `accept_by_agents`); when the judge
  cannot run, first ask for the CI review; tell the person the exact command
  `l4 yolo accept <id> --all --force --reason "<what the implementer should know>"`.
- `CHANGELOG.md` `## 0.4.18 (unreleased)`: Added (the force path), Changed (a person's `--yes`), Fixed (prompts on
  stderr, the reuse of an accepted judgement, the why-line).
- `docs/SPEC.md`: L4-YOLO-057 to L4-YOLO-067 after L4-YOLO-056; SCN-YOLO-150 to SCN-YOLO-176 after SCN-YOLO-149; row 53
  of the change table; the CLI rows of `yolo accept` (`PLAN (SUBJECT | --all --force) --reason TEXT [--withdraw]
  [--yes]`), `yolo waive` and `yolo activate`; one sentence each in L4-YOLO-005 (a holding force acceptance that covers
  every subject replaces the review, L4-YOLO-061), L4-YOLO-027 (`--yes` of a person, L4-YOLO-063) and L4-YOLO-031 (a
  person types the plan id or passes `--yes`).

## Contracts (what the tasks share; do not change one without the orchestrator)

Events (all new keys optional for older readers):
- `plan.force_accepted{plan_digest, subjects: {<subject>: {digest | digests, skipped, review_at, verdict, material}},
  reason, by, actor: "person", marker: null, confirmed: "typed" | "--yes"}`
- `plan.force_acceptance_withdrawn{reason, by, actor, marker}`
- `plan.activated` + `review: "force_accepted"` (only with a force item) and `accepted[<subject>].force: true`
- `plan.accepted` + `confirmed`, `judged_at`; `plan.finding_waived` + `confirmed`

State: `PlanState.force_accepted: dict[str, Any] | None = None` (`model.py`).

Functions:
- `accept.status_refusal(state) -> Refusal | None`
- `accept.force_subjects(plan, plan_digest_now, now, events, cfg_target, prompt_version) -> dict[str, dict]`
- `accept.force_holds(force, plan_digest_now, now) -> dict[str, bool]`
- `accept.force_line(subject, by, reason, *, holds=True) -> str`
- `accept.why_not_holds(accepted, entry, review_at) -> str`
- `findings.prior_entries(events, prompt_version, accepted=None)`
- `findings.render(..., why=None)` / `render_json(..., why=None)`: `why` maps a subject to its `why_not_holds` text
- `commands._admitted(ctx, rev, plan, plan_id, state, command)`, `commands._confirm(ctx, plan_id, text, command)` (`command` is the message prefix)
- `run_accept(app, *, plan, subject, reason, withdraw, yes, all_subjects=False, force=False)`
- `archive.render_pr_body(..., force=None)`; `tdd.FORCE_RULE`

CLI: `yolo accept`: `subject` optional; `--all` (dest `all_subjects`), `--force` (dest `force`).

## Where the code changed the decided design

1. "`unit_missing`, `schema`" are findings of a review that ran; without a review the deterministic equivalents are
   the plan file check (`_valid`), the admission of `l4 yolo activate` (`unknown_unit` for a unit folder that does not
   exist on the target) and a `MISSING` digest. The force path runs exactly these (D3).
2. The binding cannot use `accept.holds` (material and findings of a review entry): a force acceptance may have no
   entry. It binds to the plan digest and the unit digests (D4); a batch records its units' digests.
3. Activation refuses on a missing or stale review before it looks at acceptances [V: `run_activate`], so the force
   check comes first and `_review_view` skips subjects cleared by force (D5).
4. With `findings: []` the reason would not reach the implementer or the report [V: `accepted_block` and
   `_accepted_lines` skip items without findings], so a force item carries `force: true` and both render it (D6). The
   PR body has no plan state; its line comes from the carrier file (D6).
5. `--withdraw` keeps `--reason` (D1).
6. `--yes` is allowed for a person with `--force` (D8), as the later instruction recommended.
7. A plan with no review has no `plan.admitted`; the force write records one (D4).

## Risks

- Specifications no model reviewed get built and, with `merge: auto`, merged after verification. Mitigations: a
  person only, the summary of what is skipped, the reason in the implementer's prompt, the line in the PR body and the
  report, the binding to the digests.
- A wrong digest rule would let an edited spec ride on an old force acceptance. The rule is the one `inputs_changed`
  and activation already use (`current_unit_digest`); the tests edit a spec after the acceptance (SCN-YOLO-160).
- Preferring the accepted judgement keeps a person's acceptance alive when two judgements of one material disagree;
  it never accepts findings the person did not see (the binding is unchanged).
