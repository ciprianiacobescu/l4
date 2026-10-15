## Context

SPEC section 12 makes the git remote and the per-run ledger the only durable state: any runner can die and another
must continue. Section 7.5/7.7 and section 18 (L4-SEC-006) add: every harness commit carries trailers, WIP is
snapshotted to a separate branch, and every harness-side git call must be immune to repository-controlled hooks and
config. The reference environment is a GitLab 17.5.2 CE project served by a **shell-executor** runner
(`l4-runner`), which shares one filesystem between jobs - so the local `flock` is meaningful there - and
GitLab `resource_group` is the primary serialisation.

Evidence labels follow SPEC: [V] verified, [I] design decision, [U] unverified - a test or spike must confirm it
before anything relies on it.

## Goals / Non-Goals

Goals:

- A ledger, a fold and a lifecycle that make "resume after crash" a pure, testable function of files on disk and git.
- A hardened `Git` wrapper that is the only way the harness runs git; its recorded command history is test evidence
  (no `+` refspec, hooks disabled).
- Worktree per unit, reused safely, recreated from the remote on a different runner.
- M1: a local lease (flock + in-process mutex) that is correct on one runner. M2: the remote lease protocol of
  L4-LCK-001/002 with fencing.

Non-Goals:

- Choosing the phase (the orchestrator, change `implementer-tdd-loop`, calls the lifecycle API; this change only
  validates and records transitions).
- The WIP snapshot *schedule*, session resume, soft deadline (`implementer-tdd-loop`).
- The agent/gate sandbox (`sandbox-security`); this change hardens only the harness's own git calls.
- Forge API calls (labels, PRs); `forge-and-ci`. Parsing/writing `tasks.md` and `questions.md` bytes is
  `spec-providers`; this change calls it during merge-conflict resolution.
- Memory (`memory-lessons`).

## Decisions

### D1. Modules and key data structures

`l4.state.ledger`

- `class EventType(StrEnum)`: every name in L4-STA-001 plus `unit.resumed`, `budget.extended`, `push.rejected`,
  `lock.busy`, `guard.git_config`, `lessons.injected`, `lessons.curated` (the SPEC list is a minimum set; the lessons events are emitted by `memory-lessons`).
- `class LedgerEvent(BaseModel, extra="allow")`: `ts` (UTC `datetime`, serialised `YYYY-MM-DDTHH:MM:SS.ffffffZ`),
  `run_id`, `unit`, `seq` (int >= 1), `type: EventType`; payload keys sit at the top level of the JSON line.
- Run ids come from bootstrap-core's `l4.outcome.new_run_id(now, rng)` (`r-20261003T1312Z-7f3a`, SPEC 4.2); this module re-exports it and defines no second generator.
- `ledger_dir(unit_dir: Path) -> Path` = `<unit_dir>/.l4/ledger`; `ledger_path(unit_dir, run_id) -> Path`.
- `class LedgerWriter`: `open(unit_dir, unit_id, run_id, clock, redact)`, `append(type, **data) -> LedgerEvent`
  (thread-safe, one `os.write` of a full line + `fsync`, `O_APPEND`, strict `seq`), `finish(exit_code)`. First
  event is `run.started`, last is `run.finished`; appends after `finish` raise `LedgerClosed`; unknown `type` raises
  `UnknownEventType`. All string values pass the bootstrap-core redaction filter (L4-OBS-002) before writing.
- `read_ledger(unit_dir, extra_files=()) -> list[LedgerEvent]` sorted by `(ts, run_id, seq)`; a torn *last* line
  of a file (SIGKILL mid-write) is skipped and reported, any other malformed line raises `LedgerCorrupt`.
- `check_run_file(path) -> list[Problem]` (starts with `run.started`, `seq` strictly increasing, ends with
  `run.finished` unless the run is the current one).

`l4.state.fold`

- `class UnitState(BaseModel)` mirrors `l4/state@1` of SPEC 12.1. Additive fields (see Open points): `previous_phase`,
  `halt_reason`, `retry_after`, `budget_extensions` (`iterations`, `cost_usd`, `fix_rounds`), `archive_pr`,
  `breakers` (`no_progress`, `same_error`, `oscillation`, `verifier_internal_errors`).
- `fold(events: Iterable[LedgerEvent]) -> UnitState` is pure: no clock, no I/O; `updated_at` is the last event `ts`.
  Handlers live in `HANDLERS: dict[EventType, Callable[[UnitState, LedgerEvent], None]]`; an event type without a
  handler is ignored (forward compatibility).
- `dump_state(state) -> bytes`: canonical JSON, 2-space indent, field order of the model, `ensure_ascii=False`,
  trailing `\n`. Byte equality of `dump_state(fold(read_ledger(d)))` and `state.json` is the SCN-STA-01 oracle.
- `rebuild_state(unit_dir) -> RebuildResult(changed: bool, state: UnitState)` writes `<unit_dir>/.l4/state.json`
  only when the bytes differ; `state_drift(unit_dir) -> bool` is what doctor STATE-001 calls.
- `l4.state.status.run_status(app, unit, json, rebuild) -> ExitCode` is the `l4 status` handler named in bootstrap-core
  `commands.HANDLERS`; it calls `rebuild_state(unit_dir)` per unit.

`l4.state.lifecycle`

- `class Phase(StrEnum)`: the 17 states of SPEC 12.0. `TERMINAL = {merged, abandoned}`.
- `class Trigger(StrEnum)`: one id per row condition, e.g. `unit_discovered_pending`, `intake_all_pass`,
  `intake_failed`, `lease_acquired`, `required_role_unavailable`, `capacity_returned`, `questions_blocking`,
  `questions_answered`, `all_leaves_done`, `breaker_or_budget`, `verify_pass`, `verify_fail_fix`,
  `verify_needs_human`, `verify_fail_exhausted`, `fix_unit_done`, `answer_overridden`, `hand_off_pushed`,
  `ci_red_after_hand_off`, `approval_archive_ok`, `human_push_after_hand_off`, `pr_merged`, `pr_closed`,
  `pr_reopened`, `resumed`, `spec_invalid`.
- `class Edge(NamedTuple)`: `sources: frozenset[Phase] | ANY_NON_TERMINAL`, `trigger`, `target: Phase | PREVIOUS`,
  `exit_code: int | None`. `TRANSITIONS: tuple[Edge, ...]` is a literal transcription of the SPEC table (one Edge per
  source/target pair).
- `allowed_edge(phase, trigger) -> Edge | None`, `all_edges() -> list[tuple[Phase, Trigger, Phase]]` (used by the
  simulation suite to assert full edge coverage), `class IllegalTransition(Exception)`.
- `transition(writer, state, trigger, **ctx) -> Edge` resolves the target (`PREVIOUS` uses
  `state.previous_phase`), appends exactly one `phase.changed{from, to, trigger, exit_code}` event, and is the only
  code path that does so. Internal steps (merge-conflict resolution, base merge, archive re-check) never call it.
- `previous_phase` is set by the fold on `phase.changed` whose target is one of `waiting_capacity`, `halted`,
  `escalated`, `abandoned` (the source phase) and cleared when the unit leaves it.

`l4.state.idempotency` / `l4.state.reconcile`

- `step_key(unit, step, task, base_sha, spec_files_hash, template_version, profile) -> str` = hex sha256 of the
  canonical JSON array of the seven inputs (`None` encoded as `null`). `spec_files_hash(paths) -> str`.
- `reconcile(state_events, git, worktree, unit_names) -> list[Action]` with
  `Action = MarkFinished(key, commit) | RestoreWip(key, wip_sha) | Rerun(key)`, evaluated in the SPEC order:
  (1) a commit on the unit branch since base whose `L4-Step` trailer equals the key's first 12 hex -> finished;
  (2) else a WIP commit that is a strict descendant of the branch head (and, in M2, whose SHA equals the `wip_sha`
  of the last valid lock commit) -> restore; (3) else re-run.

`l4.state.resume`

- `resume_unit(writer, state, *, by, reason, is_member, extend_iterations=0, extend_cost_usd=0.0,
  extend_fix_rounds=0) -> ResumeResult`. Non-members -> `ResumeRefused("not a member")`. A unit halted or escalated on
  a budget (`halt_reason` in `iterations|cost|fix_rounds`) with no matching extension -> `ResumeRefused` naming the
  exhausted budget (CLI maps it to exit 2, message on stderr) [I]. Otherwise it appends `unit.resumed`, optional
  `budget.extended`, and (through `lifecycle.transition`) `phase.changed` back to `previous_phase`. Breaker kinds
  (`no_progress|same_error|oscillation`) need no extension; the fold zeroes `breakers` on `unit.resumed`.

`l4.vcs.git`

- `HARDENING = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never")`
  (exact SPEC L4-SEC-006 flags).
- `class Git(repo: Path | None, env: Mapping[str, str] | None)`: `run(*args, check=True, input=None, timeout=...) ->
  GitResult`; the argv is always `["git", *HARDENING, *args]`; the environment drops `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE`, `GIT_CONFIG*` inherited from the caller unless passed explicitly, and sets
  `GIT_TERMINAL_PROMPT=0`, `LC_ALL=C`. `Git.history: list[list[str]]` records every argv (credentials never appear:
  forge push credentials are injected per command by `forge-and-ci` through `extra_config`, which is redacted in the
  history). Helpers: `rev_parse`, `fetch`, `ls_remote(remote, ref) -> str | None`, `is_ancestor`,
  `config_hash() -> str`.
- `commit(message, trailers, identity, allow_empty=False)` always passes `--no-verify` and one
  `--trailer "Key: value"` per trailer.
- `l4.vcs.push`: `build_push_args(remote, specs, atomic, leases) -> list[str]` validates: no refspec starts with
  `+`; no `--force`/`-f`/`--mirror`; each `Lease(ref, expected)` renders `--force-with-lease=<ref>:<expected>`
  (empty `expected` = ref must not exist); a refspec that targets `refs/l4/locks/*` or `l4-lock/*` without a lease
  is refused. Raises `ForcedPushRefused` before any process starts.

`l4.vcs.trailers`

- `@dataclass CommitTrailers`: `unit, run_id, iteration, phase` (required), `task, tdd, agent, fallback_from, step`
  (optional). `render(t) -> list[tuple[str, str]]` in the SPEC order (`L4-Unit`, `L4-Run`, `L4-Iteration`,
  `L4-Phase`, `L4-Task`, `L4-TDD`, `L4-Agent`, `L4-Fallback-From`, then additive `L4-Step`); `parse(message) ->
  CommitTrailers` via `git interpret-trailers --parse`. `lock_commit_message(payload, run_id) -> str`: first line is
  the JSON object, then `[skip ci]`, then the `L4-Run` trailer.

`l4.vcs.names`

- `UnitNames` (frozen): from a unit id and `forge.branch_prefix`: `branch = <prefix><fw>/<name>`,
  `wip_branch = l4-wip/<fw>/<name>`, `lock_ref = refs/l4/locks/<fw>/<name>`, `lock_branch = l4-lock/<fw>/<name>`,
  `worktree = <cache>/worktrees/<key>/<fw>/<name>`, `flock_path = <cache>/locks/<key>/<fw>/<name>.lock`, `archive_worktree = <cache>/worktrees/<key>/archive/<fw>/<name>` (`<key>`: the repository key, L4-WTR-001).
  `default_cache_root(env) -> Path` delegates to bootstrap-core's `l4.config.defaults.cache_root(env)` (`$L4_CACHE`, else
  `$XDG_CACHE_HOME/l4`, else `~/.cache/l4`; never inside the repository, as L4-WTR-001 requires).

`l4.vcs.worktree`

- `class WorktreeManager(git, cache_root, remote="origin", base_branch)`: `ensure(names) -> Worktree` (fetch;
  create with `git worktree add` from `origin/<branch>` or, when absent, `-b <branch> origin/<base>`; reuse only
  when `HEAD == origin/<branch>` or `HEAD == <wip>`'s parent chain verified by `is_ancestor`; otherwise move the old
  directory to `<name>.stale-<run_id>` and recreate); `merge_base_into(worktree) -> MergeResult`; `prune(dry_run)`.
- `l4.vcs.wip`: `snapshot_wip(worktree) -> str` builds a commit from a temporary index (`GIT_INDEX_FILE` in a temp
  dir: `read-tree HEAD`, `add -A`, `write-tree`, `commit-tree -p HEAD`) and never touches the real index, HEAD or
  stash; M1 stores it under the local ref `refs/l4/wip/<fw>/<name>`; M2 pushes it, fenced, to `l4-wip/<fw>/<name>`.
  `restore_wip(worktree, wip_sha)` = `read-tree -u --reset <wip>` then `reset -q <head>` (index back to HEAD, files
  kept) [U until the test proves deletions and binary files round-trip].
- `l4.vcs.merge`: `resolve_harness_conflicts(worktree, conflicts) -> Resolution` per SPEC 12.3: ledger files never
  conflict; `state.json` is re-folded; `tasks.md` takes the union of `[x]` markers only when the task text is
  identical on both sides, otherwise `Escalate("tasks.md text differs")`; `questions.md` is merged per question ID
  keeping the newer human answer text; archive commits are reverted before the merge. Anything else -> a
  `ConflictTask` (TDD-exempt, harness-generated, reason recorded) for the implementer; after `max_task_attempts`
  failures -> `Escalate`.

`l4.vcs.locks`

- `@dataclass LeasePayload`: `unit, run_id, holder, acquired_at, expires_at, nonce` (+ `wip_sha` M2).
- `class LeaseBackend(Protocol)`: `acquire(unit, run_id) -> Lease | Busy`, `renew(lease)`, `release(lease)`,
  `verify(lease) -> bool`.
- `LocalFileLease` (M1): `fcntl.flock(LOCK_EX | LOCK_NB)` on `flock_path`, held until release or process death; the
  file body is the JSON payload for diagnostics (`holder`, `nonce`, `expires_at`). `Busy(holder)` when the lock is
  held. Crash safe: the kernel drops the flock with the process.
- `RemoteRefLease` (M2): lock commits per D4 below. `CompositeLease(local, remote)` is what runs on a shared shell
  runner; `make_lease(config) -> LeaseBackend` returns `LocalFileLease` in M1 and when `ci.platform: local`.
- `class PushCoordinator`: owns one `threading.RLock` through which *every* push (unit branch, WIP branch,
  heartbeat) passes; in M1 it performs fast-forward pushes and refreshes the local payload; in M2 it performs the
  atomic fenced push and classifies rejections (D5). `LockBusy`, `LockStolen`, `PushRejected` exceptions map to
  ledger events `lock.busy`, `lock.stolen`, `push.rejected` and run exit 0 / 1 / 1.

### D2. Ledger lives next to the unit, one file per run [SPEC STA-001]

`<unit_dir>/.l4/ledger/<run-id>.jsonl` where `unit_dir` is the unit's spec directory
(`openspec/changes/<name>/` or `.kiro/specs/<name>/`, provided by `spec-providers`). Alternatives: a repo-level
`.l4/ledger/<unit>/` (rejected: SPEC states the unit-relative path; also keeps a unit's history with the unit when
archived). [U] whether `openspec validate --strict` and `openspec archive` tolerate and carry a `.l4/` directory
inside a change folder - the first M1 task is a contract test against the pinned OpenSpec 1.14.0 CLI; if it fails the
fallback is a sibling `openspec/.l4/<name>/` (to be amended in the SPEC in this change).

### D3. State fold is a pure function; the file is a cache [SPEC STA-002]

Alternatives: keep a mutable `state.json` and patch it (rejected: it can disagree with history, and SCN-STA-02 needs
the ledger to win). The fold sorts by `(ts, run_id, seq)`; because clocks across runners can disagree, ties and
skew are resolved by that tuple only - no wall clock is read. [U] clock skew across runners can reorder events from
different runs; mitigation is that each run's events have strictly increasing `seq` and the fold never lets a later
`seq` of the same run sort before an earlier one (the sort key uses a per-run cumulative maximum of `ts`).

### D4. Remote lease commit format (M2) [SPEC LCK-001]

Lock commit: `git commit-tree` on a tree that holds only `ledger-pending/<run-id>.jsonl` (STA-004) or the empty
tree; message = JSON object on the first line (`unit, run_id, holder, acquired_at, expires_at, nonce`, plus `wip_sha`
when set), a blank line, `[skip ci]`, a blank line, `L4-Run: <run_id>`. The nonce plus an absolute UTC expiry
guarantees distinct SHAs for identical payloads in one second [V-local, research/06]. Heartbeat commits are children
of the previous lock commit. Exact commands (flags as given in SPEC):

- acquire: `git push --force-with-lease=refs/l4/locks/<fw>/<name>: origin <sha>:refs/l4/locks/<fw>/<name>`
- takeover of an expired lease: `git push --force-with-lease=refs/l4/locks/<fw>/<name>:<old-sha> origin <sha>:refs/l4/locks/<fw>/<name>`
- fenced branch push: `git push --atomic --force-with-lease=refs/l4/locks/<fw>/<name>:<current> origin <sha>:refs/heads/<branch> <hb>:refs/l4/locks/<fw>/<name>`
  (same for `refs/heads/l4-wip/<fw>/<name>`)
- release: `git push --force-with-lease=refs/l4/locks/<fw>/<name>:<current> origin :refs/l4/locks/<fw>/<name>`

[V-local, research/06]: empty expected value, contended acquire, CAS steal, stale release and atomic
branch+release behave as described on a local bare repository; a leading `+` overrides the lease (hence
`ForcedPushRefused`). [U]: GitLab 17.5.2 CE accepts `refs/l4/locks/*` custom refs and `--atomic` (doctor FORGE-005/006
and the change-0 spike settle it); that GitLab honours `[skip ci]` for a push containing several refs; that a
ref-only push (no branch) triggers no pipeline. Alternative considered: lock via a file in the unit branch (rejected:
needs a push race on the branch and cannot fence).

### D5. Classifying a rejected atomic push (M2) [SPEC LCK-001, RACE-001]

`classify(lock_ref, branch, holder_lock_sha, branch_sha_before) -> Rejection`: `git ls-remote` both refs; lock ref
differs from the holder's current lock commit -> `LEASE_LOST` (`lock.stolen`, exit 1, nothing else written); lock
ref unchanged and the branch moved -> `HUMAN_PUSH` (RACE-001 path); neither moved -> `FORGE_REJECTED` (retry once
after `push_retry_delay` = 2 s [I], then `push.rejected` with the server message, exit 1).

### D6. M1 locking = in-process mutex + local flock [I]

The user-visible M1 goal is one runner running one unit at a time. GitLab `resource_group` already serialises jobs;
the flock covers a manual `l4 run` racing a pipeline job on the shared shell runner. The remote lease adds
protection across runners and fencing and is M2. `LeaseBackend` keeps the call sites identical, so M2 swaps the
backend without touching the orchestrator.

### D7. Git hardening is a type, not a convention [SPEC SEC-006]

All harness git calls go through `Git.run`; a repository-wide test (`tests/unit/vcs/test_git_only.py`) greps `src/l4`
for `subprocess` use with `"git"` outside `vcs/git.py` and fails on a hit. Alternative: GitPython/dulwich (rejected:
extra dependency, different config handling, no `--trailer`, `--atomic`, `--force-with-lease` parity).

### D8. Worktree reuse is conservative [SPEC WTR-001]

A reused worktree must match the remote branch head or the verified WIP snapshot; any mismatch moves the directory
aside (not deleted) so unpushed harness commits survive for inspection, and a fresh worktree is created.
`doctor --fix` (GIT-001) prunes `*.stale-*` directories older than 7 days [I].

## Risks / Trade-offs

- Custom refs or `--atomic` may be refused by GitLab 17.5.2 CE [U] -> M1 does not depend on them; LCK-002 fallbacks
  are specified and doctor FORGE-005/006 report it; the change-0 spike must run before M2 lock work starts.
- `[skip ci]` handling for lock commits and ref-only pushes is [U] on GitLab 17.5.2 CE.
- `.l4/` inside an OpenSpec change folder may upset `openspec validate`/`archive` [U] -> first M1 task, D2 fallback.
- `git commit --trailer` and `--atomic` need a recent git; ENV-002 requires >= 2.40 (supports both) [I].
- `restore_wip` through `read-tree --reset` must handle deletions, renames and binary files [U] -> test first.
- Clock skew across runners (D3). Ledger corruption by a torn final line is handled; a corrupt middle line fails
  closed (`LedgerCorrupt`, exit 1).
- A single `flock` file on a network filesystem may not exclude [U]; `$L4_CACHE` is documented as a local path.
- Ledger events can contain agent text; redaction runs at write time and the writer is the only appender.

## Open points (SPEC ambiguities resolved here)

- Lifecycle (section 12.0) has no requirement ID; it is carried as `L4-STA-005` (derived) so every table row is
  traceable. SPEC should adopt the ID.
- `l4/state@1` in SPEC 12.1 is an example; additive fields (D1) are required by 12.0 (`previous_phase`) and SCN-RES-02
  (`budget_extensions`). SPEC 12.1 must be amended in this change (definition of done item 4).
- STA-003 says "trailers show the step's commit exists" but the IMP-007 trailer list has no step identity; an additive
  `L4-Step: <12 hex of the step key>` trailer is introduced.
- Trailers (L4-IMP-007), the WIP snapshot primitive (L4-IMP-011) and the git invocation flags (L4-SEC-006) belong to
  other SPEC areas but their code lives in this change's packages (`l4.vcs.trailers`, `l4.vcs.wip`, `l4.vcs.git`).
  Cross-change review (2026-10-03): each SPEC ID has exactly one owning spec delta, so the requirement blocks are
  specified by `implementer-tdd-loop` (IMP-007, IMP-011) and `sandbox-security` (SEC-006); this change's tasks cite
  those IDs in brackets and its tests (SCN-WTR-N15..N19, now listed under the owners' blocks) prove the primitives.
  `HARDENING` is defined once, here in `l4.vcs.git`; `l4.security.hardening.HARDENED_GIT_ARGS` re-exports it.
- Resume and budgets (L4-IMP-013) are owned here as a whole (the implementation map puts the RES scenarios in this
  change): ledger, fold, refusal, and the "budgets are ledger-counted" rule (part c, SCN-IMP-20). The run-start
  iteration-cap check is executed by the orchestrator (`implementer-tdd-loop` task 1.24) and the CI router
  (`forge-and-ci` task 2.31), both reading `UnitState.budget_extensions` from this change's fold. Membership of the
  actor is an input to `resume_unit`; resolving it from the forge (and the `l4:resume` label) is `forge-and-ci`.
- L4-RACE-001 is owned here (implementation map: SPEC areas STA, LCK, RACE, WTR); `forge-and-ci`'s archive pushes
  consume `l4.vcs.push.recover_from_human_push` and `PushOutcome.replan_required`.
