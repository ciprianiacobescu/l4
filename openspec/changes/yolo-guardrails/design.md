## Context

`proposal.md` quotes the owner's analysis. This change makes the harness and the skill name causes and fixes, keep
recorded reviews equal to what origin holds, stop probes from hanging, and bring in the OpenCode major gate. It is
built for 0.4.18, next to `force-accept` (L4-YOLO-057..067, SCN-YOLO-150..176, change-table row 53), which is being
implemented in parallel.

Labels: [V] verified in the code at c1994292 (or, for the gate, by a trial cherry-pick of both commits on c1994292 and
a run of its test files: 739 passed), [I] inferred.

## Goals / Non-goals

Goals: a refusal names what differs (shas, digests, files, counts) and the exact next command; a recorded review is
always a review of what origin holds; a broken configuration of the judge roles fails at load; no probe waits without
end; an agent can deliver a plan by running one script and following one `Next:` line, and stops at a person's steps.

Non-goals:
- `l4 yolo go PLAN --reason` (a single command for the whole path) is a separate change.
- The confirmation of `l4 yolo accept` and `l4 yolo waive` is force-accept's (D5).
- The texts force-accept rewrites stay force-accept's: `findings.py` `(no longer holds: the material changed)` and
  `commands.py` `(the acceptance by <by> was for other material)` (its L4-YOLO-066, design D9.2, `why_not_holds`).
- No change to how a review judges, to the prompt version or to the plan fold.

## D1. Messages name the cause and the fix (L4-YOLO-068)

### What the code says today [V]

`ReviewView("stale")` (`commands._review_view`) carries no cause. It is `stale` when the prompt version differs (early
return with `prompt_changed`), when `review_plan_digest != plan_digest(text)`, when a unit's `review_digests[u] !=
now[u]` (`now` is `_digests`: on the unit's branch on origin when it has one, else on `origin/<base>`), or when a
wanted subject (`batch:<id>` of a batch with more than one unit included) has no entry. Three places print it:
`run_activate` (`activate: review is for other inputs: run l4 yolo review <plan>`, or `… was made with an older review
prompt …`), `run_status` (`review: stale`, `review: stale (the review prompt changed)`), and `run_review`'s CI path
(`<plan>: review requested; CI reviews it at the next run on <target>`, with no word on why).

### The new module `src/l4/yolo/staleness.py`

It has pure functions plus small git readers. It does not touch `_review_view`, which force-accept rewrites.

```python
@dataclass(frozen=True)
class Divergence:
    head: str            # full sha of HEAD
    origin: str          # full sha of origin/<base>
    ahead: int           # commits on HEAD that origin/<base> lacks
    behind: int          # commits on origin/<base> that HEAD lacks
    paths: tuple[str, ...]  # of the asked paths: those that differ between origin/<base> and HEAD, in the asked order

def divergence(git, target_ref: str, paths: Sequence[str] = ()) -> Divergence | None
    # None when HEAD or target_ref does not resolve, or when they are the same commit.
    # behind, ahead = `git rev-list --left-right --count <target_ref>...HEAD`;
    # paths: `git diff --name-only <target_ref> HEAD -- <path>` per asked path, kept when non-empty (a folder counts
    # once, by its own path).
def divergence_text(d: Divergence, base: str) -> str
def divergence_verb(d: Divergence) -> str          # "push" | "pull" | "pull, then push"
def divergence_fix(d: Divergence, base: str, then: str) -> str
def unit_change(git, cfg, unit, folder, old_digest, new_digest, old_rev, target_ref, label) -> str
def plan_change(old_digest, new_digest, base, target_sha, label) -> str
def changed_files(git, old_rev: str | None, new_rev: str, folder: str) -> list[str] | None
def stale_reasons(git, cfg, plan, plan_text, plan_path, state, events, now, target_ref, folders) -> list[str]
def unit_revs(git, cfg, unit_ids, target_ref) -> dict[str, str]   # D2
def frozen_rev(events, unit, digest) -> str | None                  # D2
```

Formatting rules, shared by every message here:
- A commit sha is shown as its first 7 characters (`<h7>`, `<o7>`, `<sha7>`). A digest (16 hex characters) is shown
  as its first 8 (`<d8>`).
- Counts take the right noun: `1 commit`, `2 commits`.
- A list of paths or files names at most 3, then ` and <k> more`.
- `<where>` is `origin/<base>` when `digest.current_unit_ref` picks the target, else `its branch <branch>`. `<sha7>`
  is the sha that ref resolves to.

`divergence_text`:
- ahead only: `origin/<base> (<o7>) is <n> commit(s) behind HEAD (<h7>)`
- behind only: `origin/<base> (<o7>) is <m> commit(s) ahead of HEAD (<h7>)`
- both: `HEAD (<h7>) and origin/<base> (<o7>) have diverged: <n> commit(s) only on HEAD, <m> only on origin/<base>`
- with `paths`, it adds: `; they differ in <p1>, <p2>, <p3>[ and <k> more]`

`divergence_verb` gives `push` (ahead only), `pull` (behind only) or `pull, then push` (both).

`divergence_fix(d, base, then)` gives:
- ahead only: `git push origin HEAD:<base>, then <then>`
- behind only: `git pull --ff-only, then <then>`
- both: `git pull --rebase, then git push origin HEAD:<base>, then <then>`

`changed_files` uses `digest.file_digests` (D2). It returns the paths (relative to the repository, sorted) of the
files of `folder` that were added, removed or changed between the two revisions, as the digest reads them: harness
files are left out and task marks read as `[ ]`. It returns None when `old_rev` is None or is not a commit in this clone
(`git cat-file -e <rev>^{commit}` fails). It returns [] when the folder is missing at one side. The caller then says
nothing about files.

`unit_change(..., label)`, where `label` is one of `at the review`, `frozen at the activation` or `at the rejection`:
- `spec digest <old8> <label>, <new8> now on <where> (<sha7>)`, plus `; changed: <f1>, <f2>, <f3>[ and <k> more]` when
  `changed_files(git, old_rev, <sha of where>, folder)` is a non-empty list;
- when `new_digest` is `MISSING`: `spec digest <old8> <label>; its folder <folder> has no files on <where> (<sha7>)`.

`plan_change(..., label)`: `digest <old8> <label>, <new8> now on origin/<base> (<sha7>)`.

`stale_reasons` returns one line per cause, in this order, and [] when the review is current:
1. prompt: `review prompt <old> at the review, <new> in this harness: every subject is judged again`.
   `<old>` is `state.review_prompt_version` and `<new>` is `PROMPT_VERSION`.
2. plan file: `plan file <plan_path>: <plan_change(review_plan_digest, plan_digest(text), …, "at the review")>`.
3. each unit of the plan, in plan order, whose `review_digests.get(u) != now.get(u)`: with no recorded digest,
   `<unit>: not judged by the review`; else `<unit>: <unit_change(…, "at the review")>`. `old_rev` is
   `unit_revs[u]` of the latest `plan.reviewed` (D2), and None when that event has no `unit_revs`.
4. each `batch:<id>` that is wanted and has no entry: `batch:<id>: not judged by the review`.
5. local: when `divergence(git, target_ref, [plan_path, *folders])` has `ahead > 0` and `paths`:
   `local: <divergence_text>: <divergence_verb>, then review`.

### The messages, before and after

| # | Where | Before | After |
|---|---|---|---|
| M1 | `run_activate`, stale (inputs or prompt) | `activate: review is for other inputs: run l4 yolo review <plan>` / `activate: review was made with an older review prompt: run l4 yolo review <plan>` | `activate: the review of <plan> is stale against origin/<base> (<sha7>):`, then each `stale_reasons` line indented two spaces, then `Fix: l4 yolo review <plan>`. With a `local:` line, the fix is `Fix: <divergence_fix(d, base, "l4 yolo review <plan>")>`. |
| M2 | `run_status` text | `  review: stale` / `  review: stale (the review prompt changed)` | unchanged, then each `stale_reasons` line indented four spaces |
| M3 | `run_status --json` | `review: {state: "stale", …}` | the same, plus `review.stale`: the list of `stale_reasons` lines (the key only when the state is `stale`) |
| M4 | `run_review` CI path, a recorded review that is stale | `<plan>: review requested; CI reviews it at the next run on <target>` | first `<plan>: the recorded review is stale against origin/<base> (<sha7>):` and its lines indented two spaces (no `local:` line here: M6 says it), then the unchanged `review requested` line |
| M5 | `_file` (check, review, activate, accept) | `<who>: no plan file .l4/plans/<id>.json on origin/<base>` | the same line plus ` (<sha7>)`. Then, when HEAD holds the file and `divergence` says ahead: `Fix: <divergence_fix(d, base, "run the command again")>`. When only the working tree holds it: `Fix: commit and push .l4/plans/<id>.json, then run the command again`. Otherwise nothing more. |
| M6 | `run_review` CI path and `--local` (D4) | nothing | `warning: <divergence_text>: CI reviews origin/<base>, not your commits: push, then review` (`--local reviews origin/<base>, …` for `--local`) |
| M7 | `review --worktree --record` (D3) | the review is recorded | refusal, see D3 |
| M8 | `review --worktree --record`, the last line | `Next: git push; CI finds this review current and does not review again` | `Next: a person runs l4 yolo activate <plan> --reason TEXT` when every subject is READY or accepted, else `Next: l4 yolo findings <plan>` |
| M9 | `review --worktree` dry run, every subject clear | `Next: commit the plan file and the unit folders, then l4 yolo review <plan> --worktree --record (it judges again whatever the ledger does not hold), then git push` | `Next: commit and push the plan file and the unit folders, then l4 yolo review <plan> --worktree --record (it records the review of origin/<base>; it judges again whatever the ledger does not hold)` |
| M10 | `review --worktree --record`, uncommitted paths | last line `Commit them, or run l4 yolo review <plan> --worktree without --record.` | `Commit and push them, or run l4 yolo review <plan> --worktree without --record.` |
| M11 | `cycle._live`, plan file changed | `the plan file <path> changed after the activation` | `the plan file <path> changed after the activation: <plan_change(activated_digest, now, target, sha, "frozen at the activation")>` (the same in `_file_changed`, for the "changed" case) |
| M12 | `cycle._live`, a unit's spec changed | `the spec of <unit> changed after the activation` | `the spec of <unit> changed after the activation: <unit_change(…, "frozen at the activation")>`, with `old_rev = frozen_rev(events, unit, frozen digest)` |
| M13 | `cycle._rejected_fixed` | `the spec of <unit> changed after it was rejected` | `the spec of <unit> changed after it was rejected: <unit_change(…, "at the rejection")>` |

M11 to M13 are `plan.stopped{detail}` texts. `l4 yolo status` prints them. Each new text starts with the old one, so
a reader that matches the old text as a prefix still finds it.

Messages surveyed that already name the cause and the fix, and stay [V]: `_MOVED` (`the plan moved: run the command
again`), `_sync`'s refusals (no origin, base not on origin, not fetched), the `--record` refusal for uncommitted paths
(apart from M10), `--record --fresh` (`FreshRefused`), the rejected-unit texts of `run_review`, `run_activate` and
`resume_blocker`, the `inputs_changed` resume blocker (it names `l4 yolo review`, and the stop detail now names the
cause), every `accept.check` refusal (each has a `Fix:`), and every `run_waive` refusal. `accept.py` has no stale text.
The two acceptance texts in `findings.py:449` and `commands.py:424` belong to force-accept (Non-goals).

## D2. A review records what it read

`plan.reviewed` gets two optional keys. All three writers set them: the CI step (`cycle._review`), `run_review
--local`, and `run_review_worktree --record`.
- `target_rev`: the full sha of `origin/<base>` the review read (CI: `self._target_rev()`; `--local` and `--record`:
  the sha `_sync` returned, which `--record` has checked to be HEAD, D3).
- `unit_revs`: `{unit: full sha}` for each unit of the plan whose folder exists. The sha is the one that
  `digest.current_unit_ref(git, cfg, unit, target_ref)` resolves to, read when the review is written:
  `staleness.unit_revs(git, cfg, unit_ids, target_ref)`.

The fold does not read them. `staleness` reads them from the latest `plan.reviewed` event. `frozen_rev(events, unit,
digest)` gives `unit_revs[unit]` of the latest `plan.reviewed` whose `units[unit].digest == digest`, else None. An
activation freezes the digests of a current review [V: `run_activate` refuses a stale one], so that review's revisions
hold the frozen text. A force-accepted plan has no such review, and its stop details then name no files.

`digest.file_digests(git, rev, folder) -> dict[str, str]` gives `{path relative to the folder: sha256 hex of the
normalised content}` over the same entries that `unit_digest` hashes, with the same errors (`FolderMissing`,
`RevisionMissing`). The listing code is shared through a private `_entries(git, rev, folder)`. `unit_digest`'s value
does not change.

## D3. `--record` reviews what origin holds (L4-YOLO-069)

In `run_review_worktree`, when `record` is set, these checks run after the uncommitted-path refusal (M10) and before
`worktree.snapshot` and any judge call. `_sync` has fetched.

1. `d = divergence(ctx.git, ctx.target_ref, paths)`, where `paths` is the plan file and the unit folders (the list the
   command already builds). When `d` is not None, it refuses with exit 2:
   ```
   review: --record records what CI and l4 yolo activate read, origin/<base>, and HEAD is not that commit:
     <divergence_text(d, base)>: <divergence_verb(d)>, then review
   Fix: <divergence_fix(d, base, "l4 yolo review <plan> --worktree --record")>
   ```
   This holds even when no plan path differs, so that the recorded `target_rev` is HEAD.
2. For each unit of the plan whose branch `refs/remotes/origin/<unit branch>` exists, it compares
   `unit_digest(git, "HEAD", folder)` with `current_unit_digest(...)`. On the first that differs, it refuses with exit 2:
   ```
   review: --record: CI reads <unit> on its branch <branch> (<sha7>), where its spec digest is <d8>; HEAD has <d8'>[; changed: <files>]
   Fix: change the spec on <branch> (runbook 7.14), or let CI review: l4 yolo review <plan>
   ```
   The files come from `changed_files(git, "HEAD", <branch sha>, folder)`. Today the command prints `CI reads <unit> on
   its branch <branch>; this review read the working tree` and records anyway. That line stays for the dry run.
3. The review is then recorded with `target_rev` and `unit_revs` (D2). The last line is M8.

The dry run (`--worktree` without `--record`) is unchanged apart from M9: it reads the working tree before the push.

### Where this departs from the earlier design

review-resolution D5 and SCN-YOLO-58 made `--record` the step before the push: commit, `--record`, push, and CI finds
the review current. Item 2 of the decided scope reverses that. A recorded review must be of a commit that origin
holds. Otherwise `l4 yolo activate`, which reads origin, finds it stale; that was the reported failure. The flow
becomes commit, push, `--record`. CI does not judge again when `--record` writes first, or when CI has already
reviewed (then `--record` reuses the ledger's verdicts at no cost) [V: `prior` is the ledger, `_write_review` drops
a CI review that lost its lease to another review]. When both judge at the same time, one judging is paid twice; the
risk is accepted. L4-YOLO-026's `--record` sentence and SCN-YOLO-58 change (task B4), as do runbook 12.2a steps 4–5,
`docs/yolo-mode.md` "The review", and step 5 of the skill's `plan.md`.

## D4. The CI review warns about unpushed commits (L4-YOLO-070)

In `run_review` (not `--worktree`), after `_read_units`, it computes `d = divergence(ctx.git, ctx.target_ref,
[file.path, *folders of the plan's units known at origin])`. When `d` is not None, `d.ahead > 0` and `d.paths`, it
prints M6 before anything else the review prints. This covers both the CI request and `--local`. There is no warning
when only unrelated commits are unpushed, or when HEAD is only behind: what CI reviews is then what the person has.
This narrows the decided "warns when HEAD is ahead" to the commits that change what the review reads, to avoid noise.
The exit code does not change.

## D5. Accept up front: covered by force-accept, nothing added

The owner asked that `accept` notice there is no terminal and ask for `--yes` before it prints findings. [V] at
c1994292: `run_accept` decides the actor with `actor(environ, _stdin_tty())`, and no terminal makes the caller an
agent. Only a person reaches `_show_and_confirm`, the one place that prints findings. An agent without `--yes`
(`accept_by_agents` true) exits 2 with `no terminal to ask the plan id on: …` and has printed nothing. `run_waive` has
the same order. force-accept's L4-YOLO-064 ("MUST exit 2 at once … MUST NOT read stdin"), its D8 `_confirm` check and
its task 4.2 regression guards keep it so. This change adds no requirement, test or code here. One point goes to the
force-accept implementer, through the orchestrator: SCN-YOLO-171's test could also assert that stdout holds no
finding text.

## D6. Judge roles are checked at load (L4-CFG-006)

[V] today: `JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "fake")` is in `l4.llm.agent_judge`. A profile
outside it is skipped late, in `FallbackSelector._veto` (`profile <name> is adapter <a> cannot serve a tool-less call
here`): the role falls to the next profile, or is `RoleUnavailable`. `ladder.py:1481` filters `roles.judges` the same
way (`roles.judges: no profile of … can judge`, exit 2, in the middle of a run). Nothing checks it at load, in
preflight or in doctor.

New leaf module `src/l4/config/roles.py`. It imports nothing from `l4` and holds:
```python
JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "fake")   # moved here; agent_judge imports it from here
JUDGE_ROLES = ("judges", "verifier_agent", "clarifier", "s1_judge")
HARNESS_ADAPTERS = ("claude-code", "codex", "opencode", "kiro-cli", "command", "fake")  # a test holds it equal to factory.ADAPTERS
```
`l4/llm/agent_judge.py` replaces its tuple with `from l4.config.roles import JUDGE_ADAPTERS` and keeps the name
importable. Every existing importer keeps working. `schema.py` cannot import `agent_judge`, because `agent_judge`
imports `Profile` from it.

`L4Config` gets a `model_validator(mode="after")` named `_judge_roles_can_judge`. For each role of `JUDGE_ROLES`, in
that order, and each profile name of the chain, in order: a name that is a defined profile with `adapter` set (not
None) and not in `JUDGE_ADAPTERS` raises `ValueFree` on the first match:
```
profiles.<name> is in roles.<role>, but its adapter <adapter> cannot judge (a judge call has no tools): an adapter profile in roles.judges, roles.verifier_agent, roles.clarifier or roles.s1_judge must use one of claude-code, codex, opencode, fake; remove <name> from roles.<role>
```
The loader adds ` at $`. `<adapter>` is the adapter's name when it is in `HARNESS_ADAPTERS`, else `(not one the
harness knows)`, because `ValueFree` never echoes an unknown configured value. The allowlist is `", ".join(JUDGE_ADAPTERS)`, so
kiro-judge's change of the tuple (0.4.19) updates the text. Not affected:
- a backend profile (`adapter` None): `roles.s1_judge` holds System One and LLM backends by design (SCN-CLR-10,
  SCN-CLR-11);
- a name that is not a defined profile: preflight and CFG-002 keep that check;
- `roles.implementer` and `roles.spec_writer`.

`l4 doctor` loads the configuration before any check and exits 2 with the schema error [V: `doctor/run.py`
`load_app_config`]. So doctor names the error without a new check, and no CFG check could ever see such a
configuration. `accept.target_full_config` reads a target configuration that fails this way as "not a valid config"
and uses the defaults, with a warning, as for any invalid target configuration [V]. The late `_veto` and
`ladder.py:1481` stay as defence in depth.

## D7. The OpenCode major gate joins 0.4.18

The change folder `openspec/changes/opencode-major-gate/` comes into this branch at its spec commit (6dcddecd), in
the commit that adds this change, so that the two implementation commits apply cleanly:
- b91df9ac (A1: the probe `binary` step, the hello and the run) [V: conflicts only on that folder's `tasks.md` when
  the folder is absent; applies cleanly with it];
- b4a05956 (A2: doctor, provisioning, `prereqs.sh`, the docs) [V: applies cleanly on A1; the gate's test files pass on
  c1994292].

After the cherry-picks, the gate's CHANGELOG section `## 0.4.20 (unreleased)` moves into `## 0.4.18 (unreleased)`.
Its lines go under `### Changed` and `### Fixed`, and the 0.4.20 heading is removed. The gate's `proposal.md` and the
CHANGELOG line of its `tasks.md` 2.4 then name 0.4.18. Its SPEC row 51 and L4-OCG ids stay. The evidence file
`docs/plan/opencode-v2.md` that the gate cites stays on branch `opencode-v2`.

Two fixes from the gate's review:
1. `src/l4/provision/install.py` `_link`: `link.exists(follow_symlinks=False)` is Python 3.12 only (`pyproject.toml`
   says `>=3.11`). It becomes `not replace_files and not link.is_symlink() and link.exists()`: the same set of paths,
   an existing path that is not a symlink. The venv runs 3.12, so the failing-first test replaces `pathlib.Path.exists`
   with a function that takes no keyword (the 3.11 signature) and asserts that `_link(..., replace_files=False)` on a
   regular file raises `InstallFailed`, not `TypeError`.
2. `test_a_regular_file_at_the_node_link_is_still_replaced` calls `_link` directly. It must drive the Node install's
   loop (`_install_node`'s `for name in NODE_LINKS: _link(...)`) through `install(...)`, as
   `test_a_too_old_system_node_is_left_alone_and_extraction_is_atomic` does. The direct `replace_files=False`
   assertion moves to the 3.11 test of fix 1.

## D8. Probes never hang (L4-AVL-012)

### The mechanism [V]

`l4.proc.run_process` starts the child in its own session (`start_new_session=True`) and calls
`proc.communicate(timeout=timeout)`. `communicate` returns only at EOF on both pipes and the child's exit. A grandchild
that inherited stdout or stderr keeps the pipe open after the child has exited, and `communicate` waits for the full
timeout (60 s by default for every step). At the timeout it kills the group and calls `proc.communicate()` with no
timeout. A grandchild that left the group (an OpenCode v2 `serve --service` daemon, started by `auth list`, `models`
or `debug config` per the opencode-v2 analysis, row 8 [V there]) still holds the pipe, so that second call never
returns. `ProcRunner.run` (`agents/proc.py`) has the same unbounded `thread.join()` after its kill. Doctor's own
`system_context.run` uses `subprocess.run(timeout=…)`, which on POSIX kills the direct child at the timeout and waits
only for it [V: CPython `subprocess.run`]. It is bounded and stays unchanged.

### `run_process`, bounded

```python
EOF_GRACE_S = 2.0                 # after the direct child exits, how long its output may stay open
MAX_STREAM_BYTES = 16 * 1024 * 1024  # per stream; the rest is read and dropped
```
`Popen` is called as today (argv list, no shell, `stdin=DEVNULL`, `stdout=PIPE`, `stderr=PIPE`, binary,
`start_new_session=True`, `close_fds=True`). One loop with `selectors` reads both pipes (`os.read`, 65536 bytes) until
one of these:
- (a) both pipes reach EOF and the child has exited: the normal end;
- (b) the child has exited and `EOF_GRACE_S` has passed since: output is held. Kill the group (`os.killpg(pid,
  SIGKILL)`, errors suppressed);
- (c) the deadline (`timeout` from the start) passes: kill the group.

Then `proc.wait(timeout=5)` (a `TimeoutExpired` is suppressed) and close both read ends. Nothing ever waits for a pipe
EOF without a deadline. Results: (a) and (b) give `CmdResult(returncode, stdout, stderr)` of what was read, decoded
`utf-8` with `replace`. (c) gives `CmdResult(124, "", "timed out")`, as today. In case (a) the group is not killed
(today's behaviour): a tool that leaves a background process with closed output keeps it.

### The step timeout

- `availability.probe_step_timeout: Duration = "20s"` (new key, `AvailabilityCfg`). It is the timeout of the
  `binary`, `auth` and `quota` steps. The hello keeps `availability.probe_timeout`. The effective value is
  `min(probe_step_timeout, probe_timeout)`. `fallback.py`'s `timing` set (the keys left out of a probe's cache
  identity) gets the key.
- `ProbeCtx.step_timeout_s: float = 20.0`. `Factory.__init__` sets it from the key, as it sets `timeout_s`.
- `src/l4/availability/probes.py`:
  ```python
  class StepTimedOut(AdapterError):          # .reason holds the text
  def step_seconds(ctx) -> float             # min(ctx.step_timeout_s, ctx.timeout_s)
  def timeout_reason(cli: str, seconds: float, step: str) -> str
  def step_run(ctx, cli, step, argv, env, cwd=None) -> CmdResult   # ctx.run(argv, cwd or ctx.cwd, env, step_seconds(ctx)); 124 raises StepTimedOut
  ```
  `timeout_reason` gives `<cli> did not answer within <seconds:g> s (<step> step); <cause>: run l4 doctor`, where
  `<cause>` is `an OpenCode v2 daemon or a login prompt can cause this` for `opencode`, else `a login prompt or a
  helper process that keeps the output open can cause this`.
- Every non-hello subprocess call of a probe goes through `step_run`: `_binary` (`--version`, step `binary`; this
  replaces `<name> --version did not report a version` for a timeout only), claude `auth status`, opencode `auth list`,
  kiro `whoami`, `quota.claude_quota` (`/usage`), `quota.kiro_quota` (`/usage`). `run_rpc_session` for codex `auth`
  and `quota` gets `step_seconds(ctx)`. When it returns no answer and its time has run out (measured by the caller),
  the step raises `StepTimedOut(timeout_reason("codex", …, step))`. `openrouter_quota`'s HTTP client uses
  `step_seconds(ctx)`.
- The hello keeps `_timed(ctx, …)` with `ctx.timeout_s`. Its timeout reason becomes `timeout_reason(<cli>,
  ctx.timeout_s, "hello")` instead of `timeout`, still `failure_class="transient"`: `_hello_verdict` takes
  `timeout_text` (default `"timeout"`) and each caller (codex, claude, opencode, kiro, command) passes it.
- `ProbeLadder.run` catches `StepTimedOut` before `(AdapterError, OSError)`. The step result is
  `ProbeResult(step, False, reason=exc.reason, failure_class="transient")`, and the ladder stops there. A failed free
  step is never cached [V: `FallbackSelector._remember`], so the next selection probes again.
- `provision/readiness.py` calls `impl.probe` directly. A `StepTimedOut` at `binary` gives
  `AdapterReadiness(…, MISSING, detail=exc.reason)`. At `auth` it gives `INSTALLED_NOT_AUTHENTICATED` with
  `detail=exc.reason`.

### `ProcRunner.run`

After the existing `thread.join(timeout=5)` and the group kill, every join is bounded:
`thread.join(timeout=JOIN_AFTER_KILL_S)` with `JOIN_AFTER_KILL_S = 5.0`. When a thread is still alive after that, it
logs one warning, `a process outside the agent's process group still holds its output: the raw events end here`, and
returns the outcome. The pump threads are daemon threads.

## D9. The skill: origin first, a runbook, an error table (L4-SKL-004)

`references/operate.md` gets a new section right after its title, before `## Reading state`:
`## Delivering a plan: the runbook`. force-accept's skill edits change the `l4 yolo accept` bullet of `## Delivery
plans` and `plan.md`. This section is new text, so the two merge without overlap. The content, in this order:

1. The rule, first, in bold: **Origin is what counts.** CI and the harness read `origin/<base>`, never your working
   tree: commit and push before `l4 yolo review --record`, `l4 yolo accept` or `l4 yolo activate`. Run
   `python3 <skill dir>/scripts/yolo_preflight.py <plan>` first; it checks this and prints the one next command.
2. The person's steps, in bold: activating a plan and `l4 yolo accept … --all --force` are a person's decisions. An
   agent never runs them and never guesses another way. It stops and gives the person the exact command, with a
   `--reason` to fill in.
3. A numbered runbook:
   1. Draft: `l4 yolo draft <plan>` (`--update` for a new spec); order the units by `references/plan.md`.
   2. Validate: `l4 yolo check <plan> --worktree` (without the harness: `python3 <skill dir>/scripts/validate_plan.py`)
      and `openspec validate <change> --strict`. Optional: `l4 yolo review <plan> --worktree`, a dry run, to fix specs
      before the push.
   3. Commit and push the plan file and the spec folders to `<base>` in one commit (`references/plan.md`, Hand off).
   4. Check: `python3 <skill dir>/scripts/yolo_preflight.py <plan>`. It runs `l4 yolo check <plan>` on origin.
   5. Review: `l4 yolo review <plan> --worktree --record` (a local judge records the review of what origin holds), or
      `l4 yolo review <plan>` (CI reviews it at its next run).
   6. Findings: `l4 yolo findings <plan>`. Every subject READY or accepted: go to 9.
   7. Fix the specs as the `Resolve:` lines say, commit, push, and go to 5. This is one round.
   8. After two rounds on a subject, accept what this stack cannot fix: `l4 yolo accept <plan> <subject> --reason
      "<what the implementer should do>"`. Only a person runs it, or an agent when `yolo.review.accept_by_agents` is
      true at `origin/<base>`; otherwise stop and give the person that command. A BLOCKED subject or a blocking
      finding cannot be accepted: stop and give the person `l4 yolo findings <plan> <subject>`. When no judge can run,
      the person may force-accept the whole plan (`l4 yolo accept <plan> --all --force --reason "…"`).
   9. A person activates: stop and give the person `l4 yolo activate <plan> --reason "<why>"`.
   10. Watch: `l4 yolo status <plan>`; do its `Next:` line (`references/control-loop.md`).
4. Firm limits, as a short list: at most two rounds of spec fixes per subject, then step 8, never a third; the same
   criterion back after a fix is the stop of `references/plan.md` ("two rounds repeat the same criterion"); never
   weaken a requirement to pass a review.
5. The error table, `| Message | Cause | Fix |`, one row each:
   - `no plan file .l4/plans/<plan>.json on origin/<base>`: the plan is not pushed: its `Fix:` line (push).
   - `<plan>: not admitted, nothing to review`: admission findings: `l4 yolo check <plan>`, fix, push.
   - `review: --record records what CI and l4 yolo activate read`: HEAD is not `origin/<base>`: the `Fix:` line
     (push or pull), then `l4 yolo review <plan> --worktree --record`.
   - `review: --record: CI reads <unit> on its branch`: the unit's branch holds another spec: change it there (runbook
     7.14), or `l4 yolo review <plan>`.
   - `review: --record needs the plan file and the unit folders committed`: uncommitted edits: commit and push.
   - `review: --record --fresh …: the ledger already holds the review of this material`: a recorded verdict is not
     re-rolled: accept (step 8) or change the spec.
   - `warning: … CI reviews origin/<base>, not your commits`: unpushed commits: push, then review.
   - `review: no judge could answer, nothing was recorded`: the local judge cannot run: `l4 yolo review <plan>` (CI),
     and `l4 doctor`.
   - `<cli> did not answer within N s (<step> step)`: a daemon or a login prompt holds the CLI: `l4 doctor`.
   - `profiles.<name> is in roles.<role>, but its adapter … cannot judge`: a profile that cannot judge in a judge role:
     remove it from the role, commit, push.
   - `activate: the review of <plan> is stale against origin/<base>`: the lines name what changed: push when a `local:`
     line says so, then `l4 yolo review <plan>`.
   - `activate: <plan> has not been reviewed`: `l4 yolo review <plan>`.
   - `activate: the review is not READY for N item(s)`: steps 6 to 8.
   - `activate: <plan> is not admitted`: `l4 yolo check <plan>`.
   - `activate: plan <other> is already active, waiting or stopped on <target>`: one plan per target: wait, or a person
     cancels it.
   - `accept: acceptance is a person's decision`: an agent without `accept_by_agents`: give the person the command it
     prints.
   - `accept: <subject> was judged not READY on N version(s); 2 are needed`: one more round (step 7).
   - `accept: <subject> is BLOCKED` / `has a blocking finding`: not acceptable: fix the spec, or stop and hand it to
     the person.
   - `accept: no terminal to ask the plan id on`: an agent that may accept passes `--yes`; otherwise the person runs it.
   - `accept: --force is a person's decision`: give the person the command.
   - `waive: a waiver is a person's decision`: give the person the command it prints.
   - `resume: <unit> is still <phase>`: the cause is still there: do the `Next:` line it prints.

`SKILL.md`:
- In `## Rules`, after the `**Check before acting.**` bullet, add a bullet: **Deliver a plan by the runbook.** Run
  `scripts/yolo_preflight.py <plan>` and do the one `Next:` line it prints. Activating a plan and `--force` are a
  person's: print the command and stop. This bullet does not name `operate.md`. `test_escalate_and_note_docs` reads
  the text around the first `operate.md`.
- In `## Where to look next`, the `references/operate.md` bullet starts with "delivering a plan (the runbook from push
  to activation, the error table, the preflight script);". Its existing text, which names `l4 questions` and the note,
  stays.

`references/plan.md`: step 5 of "Check and fix the review" becomes "When every subject is READY, commit and push, then
run `l4 yolo review <id> --worktree --record` (it refuses while HEAD is not `origin/<base>`)…". The `Hand off` push
stays. This edit is in a different paragraph from force-accept's edit of `plan.md`.

## D10. `scripts/yolo_preflight.py` (L4-SKL-005)

`plugins/l4/skills/l4/scripts/yolo_preflight.py`, beside `validate_plan.py`, ships with the skill and is not copied
to `scripts/`. It uses the Python standard library only, and runs as `python3 -I`, so it cannot import its sibling:
it carries its own block-style reader of `.l4/config.yaml` (the `_top_block` family of `validate_plan.py`, copied). It
runs in the consumer repository and writes nothing but the fetched remote-tracking ref.

```
python3 yolo_preflight.py PLAN [--repo DIR] [--no-fetch] [--l4 CMD] [--json]
```
`--l4` is the harness command (default `l4`; `uvx --from … l4` works, split with `shlex`). Every subprocess runs in
its own process group with a deadline and the bounded reader of D8: git 60 s, `l4 …` 300 s, `opencode --version` 20 s.

Constants, each held equal by a test: `JUDGE_ADAPTERS` and `JUDGE_ROLES` (to `l4.config.roles`), `AGENT_MARKERS` (to
`l4.actor`), `OPENCODE_PIN = "1.18.34"` (to `l4.provision.catalog.OPENCODE_VERSION`), `OPENCODE_MAJOR = 1` (to
`catalog.SUPPORTED_MAJORS["opencode"]`, from the gate).

The checks, in this order. Each is `ok`, `FAIL`, `skip` or `info`, with a detail and, for FAIL, the fix:
1. `plan-file`: `.l4/plans/<plan>.json` exists in the working tree and parses as JSON. FAIL fix: `l4 yolo draft
   <plan>` (missing), or `python3 <this dir>/validate_plan.py, and fix .l4/plans/<plan>.json` (not JSON).
2. `clean-tree`: `git status --porcelain=v1 --untracked-files=all` lists no tracked change, and no untracked file under
   `.l4/` or a unit folder of the plan. FAIL detail: the first three paths. Fix: `commit the changes git status lists,
   then git push origin HEAD:<base>`.
3. `origin`: `origin` exists. `git fetch --quiet origin <base>` runs unless `--no-fetch`, and
   `refs/remotes/origin/<base>` resolves. `<base>` is `forge.base_branch` of `.l4/config.yaml`, else the plan's
   `target`, else `main`. FAIL fix: `git remote add origin <url>` (no origin), or `git push -u origin <base>` (no base
   there).
4. `head-is-origin`: HEAD is `origin/<base>`. FAIL detail: `divergence_text` of D1 (same words, computed here). Fix:
   `divergence_fix` with `then` = `run this script again`.
5. `on-origin`: the plan file and each planned unit's folder exist at `origin/<base>` (`git cat-file -e`, `git ls-tree`;
   folders by `validate_plan`'s `unit_folder` rule and the roots of `spec`). FAIL fix: `commit and push <first missing
   path>, then run this script again`.
6. `judge-roles`: the D6 rule on the profiles and roles of `.l4/config.yaml`. FAIL detail: the D6 text without
   ` at $`. Fix: `remove <name> from roles.<role> in .l4/config.yaml, commit and push, then run this script again`.
   A configuration the reader cannot read gives `skip` (`l4 doctor checks it`).
7. `opencode`: when a profile with `adapter: opencode` is in any role chain. It runs `opencode --version` and reads
   the first `\d+\.\d+\.\d+` (both `1.18.34` and `opencode v2.0.32`). Major 1 is `ok`. Another major is FAIL, with
   detail `opencode <v> is OpenCode v<major>; this profile runs v1 (opencode-ai 1.x)` and fix `l4 doctor --fix (it
   installs opencode-ai@1.18.34 user-locally), then run this script again`. No version within 20 s is FAIL with fix
   `l4 doctor`. Not on PATH is `skip` (`not on PATH here: a local review cannot use an opencode judge; CI's runner
   needs it`). With no opencode profile it is `skip`.
8. `accept-by-agents`: `info`. `yolo.review.accept_by_agents` and `accept_after_rounds` of `.l4/config.yaml` at
   `origin/<base>` (`git show`), defaults `false` and `2`.
9. `caller`: `info`. `person`, `agent (<MARKER>)` or `agent (stdin is not a terminal)`, by the rule of `l4.actor.actor`.
10. `harness`: `<l4> --version` exits 0. FAIL fix: `install the l4 harness (references/adopt.md), then run this script
    again`.
11. `admission`: `<l4> yolo check <plan>` exits 0. FAIL detail: its first finding line. Fix: `l4 yolo check <plan>: fix
    what it prints, commit and push, then run this script again`.
12. `review`: `info`. From `<l4> yolo status <plan> --json` (the document `l4/yolo-status@1`; the plan is
    `plans[0]`): its `status` and `review.state`, with the first `review.stale` line when stale.

Checks 10 to 12 run only when 1 to 9 have no FAIL; otherwise they are `skip` (`after the failures above`).

`Next:` is exactly one line, chosen by the first rule that applies:
1. A FAIL: the fix of the first FAIL. Exit 1.
2. The plan status is not one of `new`, `refused`, `admitted` or `reviewed`, and is not `stopped` with `inputs_changed`:
   the `next` line of the status JSON, as it is. Exit 0.
3. `review.state` is `none` or `stale`: `l4 yolo review <plan> --worktree --record` when the first adapter profile of
   `roles.judges` can run here (`claude-code` and `claude` on PATH; `opencode` with check 7 `ok`; `codex` with both
   `codex` and `bwrap` on PATH; `fake` never). Otherwise `l4 yolo review <plan> (CI reviews origin/<base> at its next
   run; then run this script again)`. Exit 0.
4. `review.state` is `current` with no problems: for a person `l4 yolo activate <plan> --reason "<why>"`; for an agent
   `a person runs: l4 yolo activate <plan> --reason "<why>" (stop here: activation is a person's decision)`. Exit 0.
5. Otherwise it reads `<l4> yolo findings <plan> --json` (the document `l4/yolo-findings@1`, its `subjects` list) and
   takes the first subject whose `verdict` is not `READY` and whose `accepted` is null or has `holds` false:
   - `accept_available`: `l4 yolo accept <plan> <subject> --reason "<what the implementer should do>"`;
   - an `accept_refusal` whose `fix` starts with `a person runs:`: that fix, then ` (stop here)`;
   - an `accept_refusal` for BLOCKED or a blocking finding, with a non-empty `persistent`: `a person decides <subject>:
     l4 yolo findings <plan> <subject> (the finding came back after a spec fix and cannot be accepted; stop here)`;
   - otherwise: `l4 yolo findings <plan> <subject>, fix the spec as its Resolve: lines say, commit and push, then run
     this script again`.
   Exit 0.

Exit 2 is a usage error: a plan id that does not match `^[a-z0-9][a-z0-9-]{0,62}$`, or a `--repo` that is not a git
work tree.

Text output: one line per check, `<result padded to 5>  <name>: <detail>`, then `Next: <line>`.
`--json` prints `{"schema": "l4/yolo-preflight@1", "plan", "base", "caller": {"kind", "marker"}, "checks": [{"name",
"result", "detail", "fix"}], "next", "exit"}`.

## D11. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`:
  - L4-YOLO-068..070 after the highest L4-YOLO requirement present (L4-YOLO-056 here, or 067 once force-accept is
    merged), and SCN-YOLO-177..191 after the highest SCN-YOLO scenario and before `### 23.21`.
  - L4-CFG-006 after L4-CFG-005, and SCN-CFG-05..07 after SCN-CFG-04.
  - L4-AVL-012 after L4-AVL-011 (group A), and SCN-AVL-21..25 after SCN-AVL-20.
  - L4-SKL-004..005 after L4-SKL-003, and SCN-SKL-09..15 after SCN-SKL-08.
  - Change-table row 54 `yolo-guardrails`, after the highest row present.
  - The `l4 yolo review` CLI row (`--record` records only when HEAD is `origin/<base>`), L4-YOLO-026's `--record`
    sentence, SCN-YOLO-58 (Given: a pushed commit no CI run has reviewed yet).
  - The ledger's `plan.reviewed` keys `target_rev` and `unit_revs`.
  - `availability.probe_step_timeout: 20s` in the §3.2 configuration sample: `scripts/check_spec.py` checks every key
    there. In §8.4, the `binary`/`auth`/`quota` rows say they run within it.
  - Each scenario is written `#### SCN-… (+|−) Title · L4-…` with **Given**, **When** and **Then**.
- `docs/yolo-mode.md` "The review": `--record` records only when HEAD is `origin/<base>`, and a stale review names
  what changed. Its command table row of `review --worktree` says the same.
- `docs/runbook.md`: 12.2's refusal list (the stale text names what changed, and the push), 12.2a steps 4–5 (commit,
  push, `--record`; the branch refusal replaces the paragraph "If a unit has a branch on origin…"), 7.4 (the probe
  timeout reason and `l4 doctor`), and the configuration note for kiro-cli in a judge role.
- `CHANGELOG.md` `## 0.4.18 (unreleased)`, lists without blank lines between items. Added: `yolo_preflight.py`, the
  runbook and the error table, `plan.reviewed{target_rev, unit_revs}`, `availability.probe_step_timeout`. Changed:
  `--record` needs HEAD to be `origin/<base>` (commit, push, `--record`); a stale review names what changed; a judge
  role with an adapter that cannot judge fails at load (breaking: remove the profile from the role); the CI review
  warns about unpushed commits; the gate's Changed lines. Fixed: a probe no longer hangs on a daemon that holds its
  output; a probe step that times out says which CLI and why; an agent run ends when an escaped helper holds its output;
  the gate's Fixed lines.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `staleness.Divergence(head, origin, ahead, behind, paths)`; `divergence`, `divergence_text`, `divergence_verb`,
  `divergence_fix`, `unit_change`, `plan_change`, `changed_files`, `stale_reasons`, `unit_revs`, `frozen_rev`
  (signatures in D1, D2).
- `digest.file_digests(git, rev, folder) -> dict[str, str]`.
- Events: `plan.reviewed` + `target_rev: str`, `unit_revs: {unit: sha}` (optional for readers).
- Status JSON: `review.stale: [str]` (only when `review.state == "stale"`).
- `l4.config.roles.JUDGE_ADAPTERS`, `JUDGE_ROLES`, `HARNESS_ADAPTERS`; `L4Config._judge_roles_can_judge`.
- `AvailabilityCfg.probe_step_timeout: Duration = "20s"`; `ProbeCtx.step_timeout_s: float = 20.0`.
- `probes.StepTimedOut(AdapterError)` with `.reason`; `step_seconds`, `timeout_reason`, `step_run`;
  `_hello_verdict(..., timeout_text="timeout")`.
- `l4.proc.EOF_GRACE_S = 2.0`, `MAX_STREAM_BYTES`; `agents.proc.JOIN_AFTER_KILL_S = 5.0`.
- Preflight JSON schema `l4/yolo-preflight@1` (D10).

## Collisions

- force-accept, `src/l4/yolo/commands.py` `run_activate`: its D5 rewrites the review checks. This change replaces
  only the body of `if view.kind == "stale":` (M1), a few lines. Whoever merges second keeps both: force-accept's
  `covered` check comes first, and when not covered, the stale branch raises M1.
- force-accept, `cycle.py`: it edits `_accepted` and `_review`'s `prior` and log line. This change adds two keys to
  `_review`'s `plan.reviewed` event and edits the stop details in `_live` and `_rejected_fixed`. These are different
  hunks.
- force-accept, the skill: it edits `operate.md`'s `## Delivery plans` bullet and `plan.md`. This change adds a new
  section at the top of `operate.md` and edits `plan.md` step 5 only. The error table names force-accept's refusal
  (`accept: --force is a person's decision`) and command. The docs test accepts `--all` and `--force` on `yolo accept`
  while the CLI lacks them, and the check switches itself off once force-accept is merged (task B8).
- force-accept, SPEC and CHANGELOG: both add to the YOLO lists, the change table (53, 54) and `## 0.4.18 (unreleased)`.
  Ids do not overlap.
- kiro-judge (0.4.19), D8: it adds `kiro-cli` to `JUDGE_ADAPTERS` in `agent_judge.py:30`. After this change the tuple
  is in `l4/config/roles.py`, and that is where its edit goes. Its CFG-011 is not used here.
- The gate: its CHANGELOG heading moves from 0.4.20 to 0.4.18 (D7). Its row 51 sits beside kiro-judge's row 50,
  which is not on this branch.

## Risks

- `--record` after the push can race a CI review of the same plan: at worst one judging is paid twice (D3).
- The load error breaks a configuration that worked with a skipped judge profile. The message names the fix, and the
  CHANGELOG says so under Changed.
- A 20 s step timeout may be short for a cold `claude -p /usage` or `kiro-cli chat /usage` on a slow host [I]. The key
  raises it. A timed-out step is `transient`, and the next selection probes again.
- The preflight's `Next:` depends on the harness's JSON (`status --json`, `findings --json`). A test runs the script
  against a fake `l4` that prints those documents. The fields it reads (`status`, `review.state`, `review.problems`,
  `review.stale`, `next`, `accept_available`, `accept_refusal.fix`, `accepted.holds`, `persistent`, `verdict`,
  `subject`) are named here, so a change of one has to update the script.
