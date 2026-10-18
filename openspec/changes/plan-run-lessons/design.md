# Plan run lessons: the judge reads big diffs in parts, an active plan gets more allowance, and the hint after an answer is true

Status: design, 2026-10-17. Harness at 0.4.14. Markers: **[V]** verified in the code of this worktree, **[I]** inferred,
**[G]** a chosen form.

## 0. The answer in ten lines

1. The judge's diff already left out `.l4/**` and the family's `verification.md` [V]; the consumer's ~202 kB of code
   and tests were over the 120000-character cap by themselves. The real fix is judging in parts (D2-D4); the
   bookkeeping list gains `questions.md`, `feedback.md` and `.serena/memories/harness/**` and is named once (D1).
2. Parts are whole files, ordered so a test sits next to its code, packed up to 120000 characters, at most 8 (D2).
3. One verdict from the parts: `fail` > `pass` > `not_verifiable` > `insufficient_evidence` per criterion (D3).
4. A diff within the cap gets one prompt with the same sections and rules as 0.4.14 and no part block; template `judge@10`. Its
   files are listed in `(key, path)` order, not git's, and lock files are one line (review N4: it is not 0.4.14's text byte for
   byte) (D2, D4).
5. What still holds is a `judge view: …` hold. It never becomes a fix unit; a reject escalates with
   `judge_view_rejected`, whose way out is split-and-restart or accept-and-retry (D5, D6).
6. `l4 yolo resume --extend-…` on an active plan writes `plan.extended` and nothing else (D7).
7. Every `--extend-…` is a person's: an agent is refused unless `yolo.extend_by_agents` is true on the base branch (D8).
8. `l4 yolo resume` and `l4 yolo status` read the plan step's own "still waits" predicate (D9).
9. The `Next:` line of a plan that waits for an answer says how to answer, or that the next run reads it; after the
   answer the wait line shows the live reason (D10).
10. The consumer repository's unit needs no repair: the 0.4.14 hold text is never raised again [I].

## 1. Current state

### 1.1 The judge's diff and its cap [V]

- `_git_diff(wb, base_sha, head)` (`src/l4/verifier/ladder.py`) runs `git diff --no-color --no-ext-diff --no-textconv
  <base>...<head> -- . :(glob,exclude)**/.l4/** :(literal,exclude)<d>/verification.md…` for each unit folder `d` of the
  family (`_unit_dirs`), decodes it, and returns `(text[:MAX_DIFF_CHARS], len(text) > MAX_DIFF_CHARS)`;
  `MAX_DIFF_CHARS = 120_000`. A scratch repository confirms that these pathspecs drop `<unit>/.l4/ledger/*.jsonl`,
  `<unit>/.l4/review-accepted.json`, a root `.l4/` and the family's `verification.md`, and keep `questions.md`.
- `_judge_step` adds the hold `the diff is longer than 120000 characters: the judge saw only the start` when the text
  was cut, and asks one judge (`_ask_judges`, which walks to the next independent judge on a limit, a served-model
  mismatch or an error). `_s1_step` uses `_git_diff` too and ignores the flag.
- `l4.state.review._NOT_SPEC = ("verification.md", ".l4", "questions.md", "feedback.md")` is the unit folder's list of
  files with a channel of their own (L4-OPS-014); SPEC L4-VER-011 calls `questions.md`, `verification.md` and `.l4/**`
  the unit's harness-owned files, and `integrity.HARNESS_OWNED` adds `.serena/memories/harness/`.

### 1.2 How the hold became a fix unit [V]

- `hold_kind` knows `scope`, `coverage` and `other`; the length hold is `other`.
- `_hold_question` tells an `other` hold to "end the reason with a sentence WHEN ... THEN ... so that a fix unit can be
  made", and the runbook §7.1 names `the diff is longer than 120000 characters` as the example.
- `_hold_finding` makes a rejected `other` hold with a `WHEN … THEN …` reason a `deterministic` finding, and
  `_candidates` (`fixunit.py`) also converts a `human` finding whose reject reason holds a scenario.
- Without a scenario the round escalates with `no_convertible_finding`, whose way out (`feedback_way_out`) is feedback
  and a retry: also no help for a diff that is too long.

### 1.3 Resume, limits and the wait for an answer [V]

- `run_resume` refuses any status but `stopped` and `waiting`; `plan.resumed{extend}` adds to `PlanState.extended`
  (`apply_extend`), which `effective_limits` and `resume_allows` read. `fold_plan` applies `plan.resumed` only from
  `stopped` or `waiting`, and a person's `plan.resumed` clears `stale_merges`.
- No code checks who runs `l4 yolo resume`; `docs/yolo-mode.md` and the skill say the agent never resumes a plan.
  `l4.actor.actor(environ, stdin_tty)` is the person-or-agent rule `accept`, `waive` and `questions` use.
- `resume_blocker` refuses a waiting plan whose current unit's phase is `awaiting_human` or `clarifying`, from
  `_Units.phases` only. The plan step's rule (`_live`, `_cause_gone`) is: the phase is in `WAIT_PHASES`, not in
  `FINISHED_PHASES`, and `next_action(facts_of(snap))[0]` is not in `_ACTIONABLE`.
- `_next_line` for that wait falls to the generic branch: `<blocker.fix>, then l4 yolo resume PLAN --reason TEXT`.
- `l4 questions answer` pushes the answer with `[skip ci]` and starts a run on the base (`start_run_line`), unless
  `--no-run` (`write_edit` in `src/l4/specs/questions_cli.py`).

## 2. Decisions

### D1 One list of the harness's bookkeeping (L4-VER-040)

New module `src/l4/verifier/diffparts.py`:

```python
BOOKKEEPING_GLOBS = ("**/.l4/**", ".serena/memories/harness/**")

def bookkeeping_pathspecs(unit_dirs: Sequence[str]) -> list[str]:
    """`:(glob,exclude)` for each glob, then `:(literal,exclude)<d>/<name>` for each unit folder `d` of the family and
    each file name of `l4.state.review.UNIT_CHANNELS` (every name but `.l4`, which the first glob covers)."""
```

`src/l4/state/review.py` gets the public name `UNIT_CHANNELS = _NOT_SPEC` (the tuple itself does not change, so the
spec-edit check is untouched). `_git_diff` passes `"--", ".", *bookkeeping_pathspecs(_unit_dirs(wb))`; its signature,
its cut and its use by `_s1_step` stay. The length that decides parts and holds is the length of this filtered diff.
A `questions.md`, `feedback.md` or `verification.md` outside the family's folders stays (project content).

### D2 The diff in parts (L4-VER-041)

`diffparts.py` also holds:

```python
MAX_PART_CHARS = 120_000   # read at call time, so a test can lower it
MAX_JUDGE_PARTS = 8

@dataclass(frozen=True)
class DiffEntry:
    paths: tuple[str, ...]   # one path, or (old, new) for a rename or a copy
    text: str                # the entry's own `git diff`, decoded utf-8 with errors="replace"; a lock file's one line
    lock: bool = False       # a lock file (`LOCK_FILES`): `text` is its summary line, never a diff

@dataclass(frozen=True)
class DiffPart:
    index: int               # 1-based
    entries: tuple[DiffEntry, ...]
    cut: bool                # the part is one entry longer than MAX_PART_CHARS, cut to it

    @property
    def text(self) -> str: ...   # the entries' texts joined, cut to MAX_PART_CHARS when `cut`

@dataclass(frozen=True)
class DiffParts:
    parts: tuple[DiffPart, ...]      # at most MAX_JUDGE_PARTS
    unseen: tuple[str, ...]          # the paths of the entries packed after the last part judged
    total_chars: int

def group_key(path: str) -> str: ...
def pack(entries: Sequence[DiffEntry]) -> DiffParts: ...
def list_entries(git: Git, base: str, head: str, pathspecs: Sequence[str]) -> list[DiffEntry]: ...
def judge_parts(git: Git, base: str, head: str, unit_dirs: Sequence[str]) -> DiffParts: ...
```

- **Listing** [G]: `git diff --name-status -z -M --no-color <base>...<head> -- . <pathspecs>`; a `R…`/`C…` record is
  one entry with both paths, any other record one entry with one path. Each entry's text is `git diff --no-color
  --no-ext-diff --no-textconv -M <base>...<head> -- :(literal)<path>…` for its paths. No parsing of unified diff
  output. A part's text is its entries' texts in order.
- **Lock files** (L4-VER-045) [owner decision 5]: `LOCK_FILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json",
  "pnpm-lock.yaml", "yarn.lock", "go.sum", "Cargo.lock", "composer.lock", "Gemfile.lock")`, matched on the base name of
  the entry's path in any folder. Such an entry is not diffed: its text is the one line `lock file <path>: <old> ->
  <new> bytes, +<added> -<removed> lines (not diffed)` (`binary` replaces the line counts for a binary file; sizes are
  those of the file at the merge base and at head, 0 when absent; the counts are `git diff --numstat`). The line is a
  few dozen characters, so a lock file is never cut and never raises a `judge view:` hold. `_git_diff` (the S1 step) is
  unchanged: it still shows the lock file's diff, cut at `MAX_DIFF_CHARS`.
- **Order** [G]: entries are sorted by `(group_key(new path), new path)`. `group_key`: the base name, lower case, cut at
  its first `.`, then without a leading `test_` and without a trailing `_test`, `_tests` or `_spec`. So
  `src/app/report.py`, `tests/unit/test_report.py`, `pkg/report_test.go` and `web/report.test.ts` all have the key
  `report` and sit side by side. The order and so the parts depend on the diff only: the same diff gives the same
  parts.
- **Packing**: in that order, a part takes the next entry while the part's length plus the entry's stays within
  `MAX_PART_CHARS`; otherwise a new part starts. An entry longer than `MAX_PART_CHARS` is a part of its own, cut to
  `MAX_PART_CHARS` (`cut: True`). After `MAX_JUDGE_PARTS` parts, the remaining entries are not packed: their paths are
  `unseen`.
- **One part**: when the filtered diff is within `MAX_PART_CHARS` (or `pack` gives one part), the step builds today's
  single prompt with no part heading, so the judge prompt of every unit under the cap has no part block and the same sections [G: it is not 0.4.14's text byte for byte: the files come in `(key, path)` order and lock files are lines; the part block
  is added only when `part` is given to `build_judge_prompt`; task 4.1 pins the old text].
- **The part prompt**: `build_judge_prompt(..., part: PartView | None = None)`; `PartView(index, count, listing)` with
  `listing: tuple[tuple[int, str, int], ...]` = (part number, path, characters) for every entry packed, then the unseen
  paths with part number 0. With `part` given, the diff section is:

  ```
  ## Diff (base...head), part K of N
  This change's diff is longer than one prompt holds, so it is judged in N parts and this prompt shows part K. Every
  file is listed below with its part; only the files of part K are shown. Judge only what this part and the gate
  report show:
  - A criterion whose code or test is not in this part: answer insufficient_evidence with the reasoning "not in this
    part". Never answer fail for it.
  - A fail must cite code shown in this part.
  - A feedback, accepted or satisfied item whose code is not in this part: answer false, with evidence that starts
    with "not in this part".
  <l4:data kind="diff parts">part 1: src/app/report.py (61234 characters) …</l4:data>
  <l4:data kind="git diff">…the part's text…</l4:data>
  ```

  The rules are harness text outside every data block; `SYSTEM` does not change. `NOT_IN_PART = "not in this part"` is
  one constant in `judge.py` that the prompt and the merge share. `PROMPT_VERSION = 10` ("10: the diff in parts").

### D3 One verdict from the parts (L4-VER-042)

New pure module `src/l4/verifier/judge_parts.py`: `merge_part_verdicts(replies: Sequence[JudgeVerdict]) ->
JudgeVerdict`. One reply returns it unchanged. Else:

- **criteria**: per part, one verdict per id as `pick_verdicts` picks it (worst first inside a part, unchanged); then
  across parts, the first `fail` in part order, else the first `pass`, else the first `not_verifiable`, else the first
  `insufficient_evidence`. Worst-first across parts would make every criterion that one part cannot see
  `insufficient_evidence`, so no unit over the cap could pass; a `pass` carries a citation, and a part that lacks the
  file says `insufficient_evidence` by rule. A `fail` still wins: it must cite code of its part, and a judge `fail`
  without a reproduced counterexample is `needs_human` in aggregation (P7), so a wrong part `fail` costs a question,
  never a FAIL [V: `aggregate_criterion`].
- **test_adequacy**: per `(test, criterion)`, the first entry with `adequate: false`, else the first entry.
- **findings**: every part's, in part order, without a repeat of `(severity, criterion, " ".join(title.lower().split()))`.
- **riskiest_assumptions**: the first three distinct strings taking the parts in turn (each part's first, then each
  part's second, …); the schema's exactly three holds because every part gave three.
- **feedback**, **accepted** (by `id`) and **satisfied** (by `task`): true (`addressed`, `holds`) when some part says
  true and no part says false with evidence that does not start with `not in this part` (case and leading space
  ignored); else false, with the evidence of the first part that said false with such evidence, else of the first
  part. A list that every part left out stays `None`.

### D4 Running the parts (L4-VER-041, L4-VER-042)

In `_judge_step` (`ladder.py`), `judge_body` becomes:

1. `parts = judge_parts(wb.git, base_sha, result.head_sha, _unit_dirs(wb))`.
2. One part: today's flow with `diff=parts.parts[0].text`, `diff_truncated=parts.parts[0].cut`.
3. Several parts: for `K` in 1..N, the prompt with that part's text and `PartView`, then `_ask_judges(vc, prompt,
   result, part=(K, N))`. `judged.status == "error"` raises `RoleUnavailable` as today. A part with `judged.verdict is
   None` appends the hold `the judge's reply was discarded (part K of N, <status>: <detail>)` and the step returns
   `(False, …)`: no part's verdict is counted (fail closed, as today's single discard).
4. `merged = merge_part_verdicts([...])`; everything after (`run.judged`, `result.judge_verdict`, `pick_verdicts`,
   counterexamples, findings, adequacy, feedback, accepted, satisfied) reads `merged`, so nothing downstream changes.

Records [G]:
- `_ask_judges(..., part: tuple[int, int] | None = None)` adds `part=K, parts=N` to each `verify.judge` it emits.
- `VerifyResult.judge_parts: list[dict[str, Any]]` (default empty): per part `{part, files, chars, profile, calls,
  reply, prompt_sha256}`; `verdict.json` writes it as `judge_parts`.
- `result.prompt_sha256`: one part, the prompt's own; several, the sha256 of the parts' sha256 values joined with
  `\n` in part order. `result.prompt_template = "judge@10"`.
- `result.judge_reply`: the worst of the parts' in the order `discarded`, `retried`, `repaired`, `valid`.
- `verification.md`: the judge line gets `, judged in N parts` and one line per part
  (`  - part K: F file(s), C characters, profile P, reply R`).
- A judge replaced in the middle of the parts (`next_judge`) judges the remaining parts; the parts already judged are
  kept, since every judge `next_judge` yields is independent of the implementers (L4-VER-001). `result.judge_profile`
  and `vc.independence` are those of the last part; each part's profile is in `judge_parts` [G; cost argues against
  judging the earlier parts again].
- Step 9 stays one ladder step (L4-VER-011): a run that ends in the middle of the parts judges every part again.

### D5 The holds that remain are holds on the judge's view (L4-VER-043, L4-VER-044)

Two texts, made in `_judge_step` from `parts` (fixed; no character counts in them, so a small change of size does not
make a new hold id):

- a cut part: ``judge view: the diff of `<path>` is longer than one part (120000 characters): the judge saw only its
  start`` (the number is `MAX_PART_CHARS`);
- unseen entries: ``judge view: the diff needs more than 8 parts of 120000 characters: the judge did not see `<p1>`,
  `<p2>`, … (+K more)`` (at most five paths, in pack order).

`verdicts.py`: `HoldKind = Literal["scope", "coverage", "judge_view", "other"]`; `hold_kind` returns `judge_view` for a
text that starts with `judge view: ` and for `LEGACY_LENGTH_HOLD = "the diff is longer than 120000 characters: the judge
saw only the start"` (a round on 0.4.14 resumed after the upgrade can still carry it). `hold_subjects` returns the
backticked paths of a `judge_view` hold.

`_hold_question` for `judge_view` ends with, instead of the accept/reject sentence of the other kinds:
"The judge could not see all of the diff, so it could not judge the files this hold names. Answer `accept` if you
checked those files yourself and the unit can go on as it stands. A fix unit cannot shrink the diff, so `reject` stops
the unit (escalated with judge_view_rejected): then split the change into smaller units." It never asks for a
`WHEN … THEN …`.

`_hold_finding` for `judge_view`: always `source="human"`, `Severity.MAJOR`, title `JUDGE_VIEW_REJECTED_TITLE =
"Rejected hold: the judge could not see all of the diff"`, detail `A fix unit cannot shrink the diff: split the change,
or accept the hold once a person checked the files. Hold: …` plus `rejection_note(verdict)`, whatever the reason says.

`fixunit._candidates`: a finding whose title is `JUDGE_VIEW_REJECTED_TITLE` is skipped before the scenario logic with
`<id>: a hold on the judge's view of the diff: a fix unit cannot shrink the diff`, and its reject's question goes to
`unconverted` (so a feedback-only spawn consumes it, L4-VER-016, and the hold is asked again on the fixed code).

### D6 The escalation names its own way out (L4-VER-044)

`l4.state.next_step`: `JUDGE_VIEW_REJECTED = "judge_view_rejected"` and

```python
def judge_view_way_out(unit: str) -> str:
    return (
        "a fix unit cannot shrink the diff the judge could not see; split the change into smaller units (then "
        f"l4 restart --unit {unit} --reason TEXT), or, once you checked the files the hold names, replace the answer: "
        f"l4 questions answer Q-NNN --unit {unit} --text \"accept ...\" --replace, then l4 retry --unit {unit} "
        "--reason TEXT"
    )

def way_out(unit: str, halt_reason: str | None) -> str | None:
    """`feedback_way_out` for no_convertible_finding, `judge_view_way_out` for judge_view_rejected, else None."""
```

`next_step` (escalated), `_refuse_stopped` in `orchestrator.py` and `halted_section` in `ci/resume_label.py` call
`way_out` instead of testing `NO_CONVERTIBLE_FINDING` themselves. The sticky note for `judge_view_rejected` is
`### Escalated: <why>`, a blank line, `To go on: <judge_view_way_out>.` (no feedback sentence).

`fixloop.decide_fix`: where a FAIL with no group would escalate with `no_convertible_finding`, it escalates with
`JUDGE_VIEW_REJECTED` and the reason `a person rejected a hold on the judge's view of the diff: a fix unit cannot shrink
the diff` when a finding of the round has the title `JUDGE_VIEW_REJECTED_TITLE`. A round with other convertible
findings spawns its fix unit as today; the reject stays in force and the hold, if raised again, fails the next round.

What the person sees: a 202 kB diff gives a verdict with no hold, `verification.md` says `judged in 2 parts`. A 300 kB
`uv.lock` gives `Hold H-…: judge view: the diff of `uv.lock` is longer than one part …`, whose question says what
accept and reject do. A reject gives `escalated` and `Next: a fix unit cannot shrink the diff …`.

### D7 `resume --extend-…` on an active plan writes `plan.extended` (L4-YOLO-050)

Chosen over a new `l4 yolo extend` command [G]: L4-YOLO-014 and every doc already name `l4 yolo resume --extend-…` as
the one way to more allowance, and the person in the lesson typed exactly that. The verb is stretched, so the output
and the event say plainly that nothing resumed.

`run_resume` (`src/l4/yolo/commands.py`), for `state.status == "active"`:

- no `--extend-…`: exit 2, `resume: <plan> is active: only a stopped or waiting plan resumes; to raise a limit of the
  active plan, pass --extend-cost USD, --extend-runs N, --extend-attempts N or --extend-deadline ISO`.
- with one or more (the person check of D8 has passed already): `_sync` and the plan file as today, then `before =
  effective_limits(state, fallback)` and `after` = the same on a deep copy with `apply_extend`. Refused (exit 2,
  nothing written) when an option changes nothing: `resume: <plan> has no cost limit: --extend-cost changes nothing`,
  `… has no run limit: --extend-runs changes nothing`, `… has no deadline: --extend-deadline sets none`,
  `--extend-deadline <ISO> is not later than the deadline in force <ISO>`. `--extend-attempts` always raises.
- then `_append(store, [_event("plan.extended", by=ctx.who(), actor=who[0], marker=who[1], agent_key=<bool>, reason=…,
  extend=extend.as_data(), limits_before=…, limits_after=…)], read.head)`, where a limits dict is `{"cost_usd",
  "runs", "attempts", "deadline"}` (`attempts` = `max_unit_attempts` plus the `*` extension; `deadline` as
  `%Y-%m-%dT%H:%M:%SZ` or None). No run is started, whatever `--no-run` says.
- output: `<plan>: limits raised on the active plan (plan.extended): runs 90 -> 110` (one `name old -> new` per limit
  that changed, joined with `; `; cost as `$10.00`, unlimited as `unlimited`), then `nothing resumed and no run
  started: CI advances the plan at its next run`.

`fold_plan` (`src/l4/yolo/state.py`): `plan.extended` → when activated and not final, `apply_extend(state,
data.get("extend"))`; nothing else (status, wait and stop fields, `stale_merges`). Before the activation it is
ignored. `effective_limits`, `reached`, `resume_allows` and `_live_usage` need no change.

`l4 yolo status`: `_describe` adds `extensions` (each `plan.extended` after the latest `plan.activated`: `at`, `by`,
`actor`, `agent_key`, `reason`, `extend`, `limits_before`, `limits_after`); `_render` prints one line each,
`  extended: runs 90 -> 110 by alex@example.com (person): three units left` (`(agent, yolo.extend_by_agents)` when the
key let an agent). The `Next:` of an active plan becomes
`nothing: CI advances the plan at each run (l4 yolo resume <plan> --reason TEXT --extend-runs N raises a limit before
it is reached; l4 yolo cancel <plan> --reason TEXT stops it)`.

### D8 Raising a limit is a person's decision, unless the base branch says otherwise (L4-YOLO-051)

Today it is a documented rule only [V]. From this change, `run_resume` checks `l4.actor.actor(app.environ,
_stdin_tty())` whenever an `--extend-…` is given, on an active, waiting or stopped plan, after `_extend` has validated
the values and before `store.read()`. A person goes on. An agent goes on only when `yolo.extend_by_agents` is `true`
in `.l4/config.yaml` at `origin/<base>` [owner decision 1]: the key is a bool in `YoloCfg` (`L4Config.yolo`), default
`false`, read like `yolo.review.accept_by_agents` (`accept.target_full_config`, which fetches nothing itself: the
command syncs `origin` first; the base branch's file, never the working tree or a unit branch; absent or invalid file:
the default). Otherwise exit 2, nothing written:
`resume: raising a plan's limits is a person's decision (<marker> is set | stdin is not a terminal)` and
`Fix: a person runs: l4 yolo resume <plan> --reason "..." <the same --extend-… options>; or set yolo.extend_by_agents:
true in .l4/config.yaml on the base branch (a pushed change a person can see)`. A resume without `--extend-…` keeps
today's rule. `plan.extended`, and a `plan.resumed` that carries an `extend`, record `actor`, `marker` and
`agent_key` (true only when an agent extended because the key allowed it), so the audit shows who raised a limit and
under which rule. Documented where the other two keys are (SPEC configuration listing, runbook, `docs/yolo-mode.md`,
the skill's `operate.md`, CHANGELOG).

### D9 One "still waits" predicate for the step, the resume and the status (L4-YOLO-052)

`src/l4/yolo/cycle.py` gets, at module level,

```python
ACTIONABLE = _ACTIONABLE

def still_waits(snap: UnitSnapshot) -> bool:
    """The unit waits for a person or for capacity with nothing to run: the rule of `_live` and `_cause_gone`, and
    of `l4 yolo resume` and `l4 yolo status` (L4-YOLO-052)."""
```

(the phase is in `WAIT_PHASES`, not in `FINISHED_PHASES`, and `next_action(facts_of(snap))[0]` is not in
`_ACTIONABLE`; the planner is imported inside the function, as `_unit_action` does). `_live` and `_cause_gone` call it;
their behaviour does not change (the existing cycle tests pass untouched).

`src/l4/yolo/commands.py`: `_Units.answered: set[str]`, filled in `_read_units` with each unit whose snapshot phase is
`awaiting_human` or `clarifying` and for which `still_waits(snapshot)` is false: its answers are pushed and no run has
read them. `resume_blocker(..., answered: Collection[str] = ())` (keyword only): for a waiting plan whose current unit
is in `answered`, no blocker; the resume records `plan.resumed` and starts the run that reads the answers, as the step's
`_wake` would at that run. Otherwise the refusal keeps its text and adds `; a waiting plan continues by itself at the
run that reads the answer, so no resume is needed after it`. The `waiting_capacity` branch is unchanged.

### D10 The `Next:` line of a plan that waits for an answer (L4-YOLO-053)

`_next_line(plan_id, state, view, blocker, *, unit_phase: str | None = None, answered: bool = False, start: str = "")`;
`_describe` passes the current unit's phase from `units.phases`, `state.current in units.answered` and
`start = how_to_start(ctx.app, ctx.cfg, ctx.target)` (`l4.state.retry`). For a waiting plan whose current unit is
`awaiting_human`, before the generic branch:

- open questions: `answer the questions of <unit>: l4 questions --unit <unit>, then l4 questions answer Q-NNN --unit
  <unit> --text TEXT (it pushes the answer and starts a run); the plan continues by itself at the run that reads the
  answer, no resume is needed`;
- answers pushed: `nothing: the answers of <unit> are pushed and the next run reads them; the plan then continues by
  itself (to start that run now: l4 yolo resume <plan> --reason TEXT, or <start>)`.

`l4 questions answer` keeps its output (`run started on <base>`, `Next: l4 status --unit U`).

### D11 A plan stopped on a unit with its own way out names it first [owner decision 6]

`resume_blocker(..., halt_reasons=…)` (`_Units.halt_reasons`: unit id to the `halt_reason` of its snapshot): for a plan
stopped with `unit_escalated` on a unit in phase `escalated`, `way_out(unit, halt_reason)` (D6) is the blocker's message
tail and its `fix` (so the `Next:` line reads `<way out>, then l4 yolo resume PLAN --reason TEXT`) when it is not
None (`judge_view_rejected`, and `no_convertible_finding`, whose own `l4 status` line already says the same); any other
cause keeps `run l4 retry --unit U first`. A `halted` unit keeps it too.

### D12 The wait line after an answer [owner decision 8]

`_describe` sets `wait_detail` to `ANSWER_RECORDED = "the answer is recorded and the next run reads it"` when the plan
waits and its current unit is in `_Units.answered` (D9), in the text and in `--json`; while the question is open the
detail recorded with `plan.waiting` stands.

### D13 An accept is bound to the content the judge did not see (L4-VER-046, review M1)

`diffparts.blob_ids(git, head, paths)` (a few `git ls-tree`) gives the head blob of each file a hold covers.
`ladder._hold_views(parts, blob_of)` returns, per `judge view:` hold text, `HoldView(sha, paths)`: `paths` is every file
the hold covers (the cut file, or ALL unseen files, not the five its text names), and `sha = sha256(text NUL
"path TAB blob" lines)`. The hold id stays `hold_id(text)`. `VerifyResult.hold_views` keeps `{text: {sha, paths}}` (in
`verdict.json` and restored on a reused round). `_finalize` builds `current[hold_id] = hold_sha256(hold, hold_views)` and
`raise_verdict_questions(hold_views=...)` raises the question with that `text_sha256`, so an accept of other content is
not in force (`effective_verdicts` compares the two) and the hold is asked again. A hold of another kind keeps
`finding_sha256(hold_id)`. `_hold_question(paths=...)` lists every unseen file, at most `QUESTION_MAX_PATHS = 100`, then
`and K more unseen files: see verification.md`.

### D14 The listing is bounded and the content is read once (L4-VER-047, review M3)

`list_entries` runs one `git diff --name-status -z -M` and one `git diff -M`, split at `^diff --git ` (the same count,
else one diff per file). A lock file's line is made from its own block. The text kept per entry is at most
`MAX_PART_CHARS + 1` characters and the text of the entries past `RETAIN_PARTS * MAX_PART_CHARS` characters is not kept,
only its length (`DiffEntry.chars`); `_refill` fetches again, per file, the few that a part shows. `part_listing` lists
at most `LISTING_MAX_LINES = 200` files and no more than 1/`LISTING_SHARE` (4) of a part's characters, then
`+K more files: see verification.md` (`PartView.more`); `pack(reserve=listing_chars)` keeps that room free in every part
(applied only to a diff of several parts). `verification.md` lists up to 2000 files by part (`## Files by part`) and
`verdict.json` all (`judge_files`).

### D15 A test lands with the code it imports (review M2) and a part judges the code it shows

`pack` sorts by `(key, path)`: the key is the name key; for a test with no code of its name in the diff it is the key of the
first module its added lines import that is in the diff (`from a.b import c`, `import a.b`, `from "./b"`, `require("./b")`:
last segment, lower case). The part rule no longer says `code or test`: a criterion whose code the part does not show is
`insufficient_evidence`; one whose code it shows is judged there, whichever part holds its test.

### D16 Adequacy follows the sight of the part (review N6)

A part that cannot see a test cannot call it inadequate: `judge_parts._rank` makes an entry with reason `not in this part`
the weakest, a real `adequate: false` the strongest; a test only blind parts called inadequate is adequate. The part
rules say: a test whose code is not in this part is left out of `test_adequacy`.

### D17 The key is read from the plan's own target (review N1) and a cost is finite (review N2)

`_plan_config(ctx, plan_id)` reads the plan file on the configured base branch; when its `target` is another branch, or
the file is missing or invalid, an agent has no key (note: `the base branch X of the configuration differs from the
plan's target Y`) and `.l4/config.yaml` is read at `origin/<plan.target>`. The same helper serves
`yolo.review.accept_by_agents` (accept, findings, waive). `_extend` refuses a cost that is `nan`, `inf` or `-inf`.

### D18 Lock files (review N3, refines owner decision 5)

An entry is a lock file only when the old and the new base name are both in `LOCK_FILES`; a source file renamed to
`go.sum` is diffed. The line names the old path of a rename and adds `N touch a source field` (changed lines that hold
`resolved`, `registry`, `source`, `url`, `integrity`, `hash` or `checksum`) and `hosts: a, b` (distinct hosts of the URLs
in those lines, at most 10).

### D19 Answered units, the answer step, the extensions list, mixed rejects (review N5, N7)

`answered_units` is the units in `awaiting_human` or `clarifying` that no longer wait AND whose facts hold
`answers_unblock` or `verdicts_ready`: a clarifying unit with nothing answered is not "the answer is recorded".
`answer_fix_of` gives, for a unit whose answer is invalid, dismissed or a draft, `l4 status`'s step plus the `--replace`
command; `_next_line(answer_fix=...)` puts it first. `_extensions(events)` replays the fold: the `plan.extended` after
the first activation and before the plan was final. `_no_task_cause` returns `no_convertible_finding_and_judge_view_rejected`
when a rejected judge-view hold and another unconvertible human finding are in one round; `way_out` names both ways out.

## 3. Risks

- **Cost.** A diff over the cap now costs up to 8 judge calls a round; before, it cost one call and a person's answer
  every round [I].
- **What no part sees.** A criterion whose code is in one part and whose test is in another can get
  `insufficient_evidence` in both, then `needs_human`: a person's question, as before, never a FAIL. The name key and
  the gate report in every part make this rarer [I].
- **A part's wrong `pass`.** A part that sees the test and the gate report but not the code can pass a criterion; the
  same risk exists for one judge today, and traceability still needs a discriminating passing test [I].
- **Two judges in one round.** After a limit in the middle of the parts, the parts have different profiles. Both are
  independent of the implementers; the report names the last one and `judge_parts` names each [G].
- **The person check refuses a person without a terminal** (a script, a pipe on stdin). The refusal says to run it
  from a terminal, or to set `yolo.extend_by_agents`; `| tee` on stdout stays a person's command (`l4.actor`) [V].
- **The new hold ids.** The `judge view: …` texts hash to new `H-` ids, so an answer given to the 0.4.14 hold does not
  carry over; that hold is never raised again, so nothing waits on it [I].
- **The consumer repository's unit.** Its next round on 0.4.16 judges in parts; the rejected old hold is not raised
  again, so its reject finds nothing to apply to [I].

## 4. Rejected alternatives

- **A new `l4 yolo extend` command.** Clean verb, but a second way to the same allowance, a new row in the command
  table, the dispatch table and the skill, and the command the person typed would still refuse (D7).
- **A larger cap, or a configuration key for it.** Moves the limit without removing it; a long prompt costs the same as
  several parts and judges worse [I].
- **Cutting inside a file.** A judge cites `file:line`; a part that holds half a file invites wrong `fail`s. A file is
  the unit of a part, and a single file over the cap is a person's hold (a lock file is not a file in that sense: it is one line, D2).
- **A summary of the other parts in each prompt.** An unverified model-written layer between the diff and the judge.
- **Merging worst-first, as `pick_verdicts` does inside one reply.** Every criterion one part cannot see would be
  `insufficient_evidence` (D3).

## 5. Decisions of the owner (were open questions)

1. **Who may raise a limit.** A person only, for every `--extend-…` (active, waiting and stopped plans), with a config
   key `yolo.extend_by_agents` (bool, default `false`) that lets an agent extend, like `yolo.review.accept_by_agents`
   and `clarifier.answer_by_agents`. The event records the actor and whether the key allowed it (D7, D8).
2. **`resume --extend-…` or `l4 yolo extend`.** `l4 yolo resume --extend-…` on an active plan, as designed (D7). No
   separate command.
3. **The limits of the parts.** 120000 characters a part and 8 parts stay constants.
4. **The discarded-reply hold.** Out of scope; one line in the follow-ups below.
5. **Lock files.** Included: ten lock files are one line each for the judge, never diffed, never a hold (D2, L4-VER-045,
   SCN-VER-140..142, 144).
6. **The plan's stop line for an escalated unit.** Included for `judge_view_rejected` (and, with the same function,
   `no_convertible_finding`): D11, L4-YOLO-055, SCN-YOLO-143.
7. **A negative scenario for L4-VER-040.** SCN-VER-143, from the ids SCN-VER-140..144 that the owner reserved.
8. **The stale wait detail.** Included: D12, L4-YOLO-054, SCN-YOLO-142.

SCN-VER-140..144 are used (140, 142, 144 and 141 for L4-VER-045 and L4-VER-043, 143 for L4-VER-040). The scenarios the
owner's decisions added outside that reservation are SCN-YOLO-141 (the key), SCN-YOLO-142 and SCN-YOLO-143.

## 6. Follow-ups (not in this change)

- The hold `the judge's reply was discarded (…)` is an `other` hold whose question still asks for a `WHEN … THEN …`, the
  same trap as the old length hold: a reject with a scenario makes a fix unit that cannot make the judge answer. A next
  change can make it a `judge_view`-like hold (a person's decision, no fix unit).
