## Why

A consumer repository got stuck delivering a plan on harness 0.4.17. The owner's analysis of that session found two
kinds of cause.

The skill explains what each `l4 yolo` command does, but not what makes it fail. It says activation is a person's
step, so an agent that is told to activate starts guessing. It sets no limit on spec-fix rounds. Nothing tells a weaker
model the order of the steps.

The harness's own messages name a symptom, not a cause. `activate: review is for other inputs: run l4 yolo review p1`
does not say that `origin/<base>` is two commits behind the local HEAD, or which spec changed. `l4 yolo review --worktree
--record` records a review of a local commit that CI and `activate` never see until it is pushed. A `kiro-cli` profile
in `roles.judges` loads and is skipped late, at selection. A probe of an OpenCode v2 binary can hang the availability
check: v2 starts a daemon that keeps the probe's output pipe open, and `l4.proc.run_process` waits for that pipe without
end. The OpenCode major gate (`opencode-major-gate`, built on branch `opencode-v2`) is ready and joins this release.

## What Changes

- **The messages name the cause and the fix** (L4-YOLO-068). A stale review names what differs: the plan digest at the
  review and now, each unit whose spec digest changed (both digests, where it is read, the short sha, and the files
  that changed), a subject the review did not judge, a review prompt change, and whether the local HEAD is ahead of
  `origin/<base>`. `activate`, `status` (text and `--json`), `review`, the "no plan file on origin" refusal and the
  `inputs_changed` stop details use it. Every review records the revisions it read (`plan.reviewed{target_rev,
  unit_revs}`), so a later message can name the files.
- **`--record` reviews what origin holds** (L4-YOLO-069). `l4 yolo review PLAN --worktree --record` fetches and then
  refuses, before any judge call, when HEAD differs from `origin/<base>`. The refusal names both short shas, the
  commits ahead and behind, and the plan paths that differ, and says "push, then review". It also refuses when CI
  reads a unit on its branch and that branch holds another spec digest. The documented flow becomes commit, push,
  `--record`.
- **The CI review warns about unpushed commits** (L4-YOLO-070). `l4 yolo review PLAN` and `--local` print a warning
  when HEAD is ahead of `origin/<base>` and the commits change the plan file or a unit folder.
- **Judge roles are checked at load** (L4-CFG-006). Configuration load rejects an adapter profile in `roles.judges`,
  `roles.verifier_agent`, `roles.clarifier` or `roles.s1_judge` whose adapter cannot answer a tool-less judge call
  (not in `JUDGE_ADAPTERS`). The error names the profile, the role and the allowlist. `l4 doctor` exits 2 with the same
  text. Backend profiles are not affected.
- **The OpenCode major gate joins 0.4.18** (`opencode-major-gate`, L4-OCG-001..004). Its two implementation commits
  are cherry-picked, with two fixes from review: the no-replace link guard runs on Python 3.11, and the Node-link test
  goes through the Node install.
- **Probes never hang** (L4-AVL-012). Every probe subprocess runs in its own process group. Output is read until the
  direct child exits plus a short grace, never until a grandchild closes the pipe. At the timeout the whole group is
  killed. The `binary`, `auth` and `quota` steps get a short timeout (`availability.probe_step_timeout`, 20 s), and the
  hello keeps `probe_timeout`. A step that times out fails with a reason that names the CLI, the seconds, a likely cause
  and `l4 doctor`. An agent run whose escaped helper holds its output pipe ends too.
- **The skill gets a runbook and an error table** (L4-SKL-004). `references/operate.md` starts with the rule that
  origin is what counts. It then gives a numbered runbook for delivering a plan, firm limits (at most two rounds of
  spec fixes per subject, then accept what this stack cannot fix), and an error table (message → cause → fix). The skill
  says that activation and force-accept are a person's steps: the agent stops and hands the person the exact command.
- **`yolo_preflight.py`** (L4-SKL-005), beside `validate_plan.py`, uses the standard library only. It checks a clean
  tree, HEAD equal to `origin/<base>`, the plan paths on origin, the judge allowlist, the installed OpenCode major,
  `accept_by_agents` and the caller. It then asks the installed harness for admission and the review state, and prints
  each check with ok or FAIL and exactly one `Next:` command.

Accepting without a terminal is not part of this change. force-accept already requires the no-terminal refusal to
come before anything is printed (L4-YOLO-064). Design D5 says why nothing is added here.

## Impact

- Code: `src/l4/yolo/staleness.py` (new), `src/l4/yolo/digest.py` (`file_digests`), `src/l4/yolo/commands.py`
  (`_file`, `run_review`, `run_activate`'s stale branch, `_describe`/`_render`), `src/l4/yolo/review_worktree.py`,
  `src/l4/yolo/cycle.py` (`_review`'s event, the `inputs_changed` stop details), `src/l4/config/roles.py` (new),
  `src/l4/config/schema.py`, `src/l4/llm/agent_judge.py` (imports `JUDGE_ADAPTERS`), `src/l4/proc.py`,
  `src/l4/agents/proc.py`, `src/l4/agents/base.py` (`ProbeCtx.step_timeout_s`), `src/l4/agents/factory.py`,
  `src/l4/availability/probes.py`, `src/l4/availability/quota.py`, `src/l4/availability/fallback.py`,
  `src/l4/agents/opencode.py`, `src/l4/agents/kiro_cli.py`, `src/l4/agents/command.py`,
  `src/l4/provision/readiness.py`; the cherry-picked gate (`src/l4/versions.py`, `src/l4/provision/*`,
  `src/l4/doctor/*`, `scripts/runner/prereqs.sh`).
- Skill: `plugins/l4/skills/l4/SKILL.md`, `references/operate.md`, `references/plan.md`,
  `scripts/yolo_preflight.py` (new).
- Ledger: `plan.reviewed` gets the optional keys `target_rev` and `unit_revs`. Older ledgers fold unchanged. Older
  reviews still give every message, without the file names.
- Configuration: new key `availability.probe_step_timeout` (default `20s`). **Breaking:** a configuration with an
  adapter profile that cannot judge in a judge role (for example `kiro-cli` in `roles.judges`) no longer loads. Remove
  the profile from that role. kiro-cli becomes a judge in 0.4.19 (`kiro-judge`).
- Behaviour change: `--record` needs HEAD equal to `origin/<base>`. Before, the flow was commit, `--record`, push. Now
  it is commit, push, `--record`. SCN-YOLO-58 and the `--record` sentence of L4-YOLO-026 change.
- Spec: L4-YOLO-068..070 with SCN-YOLO-177..191; L4-CFG-006 with SCN-CFG-05..07; L4-AVL-012 with SCN-AVL-21..25;
  L4-SKL-004..005 with SCN-SKL-09..15; change-table row 54. The gate keeps its own L4-OCG-001..004, SCN-OCG-01..10 and
  row 51.
- No prompt version change and no runtime dependency.
