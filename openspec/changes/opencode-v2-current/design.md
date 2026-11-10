## Context

`opencode-v2` (row 68, 0.4.28) built `OpenCodeV2Adapter` from recordings of `@opencode/cli` 2.0.32 made with no key, and
shipped it experimental with eleven [U] rows on named fallbacks (its design D13, U1 to U11). Its live validation (groups
B8 and B9) was deferred (its amendment E8). This change rests on a live check of 2026-11-10 against `@opencode/cli`
2.2.6 (npm `latest` since 2026-11-06), which drove L4's own code (amaster `e407590d`, release 0.4.55) with the real
binary:

- **mac**: macOS arm64, no sandbox (`wrap=None`), an isolated HOME and isolated XDG directories.
- **box**: a Linux arm64 container (Debian bookworm, bubblewrap 0.8.0) with L4's real `BwrapSandbox` and an agent
  `SandboxSpec` built like `Workbench.agent_spec` (`CREDENTIAL_PATHS`, `spec_paths` tool paths). opencode2 was installed
  the way the catalog installs it.
- Models: `opencode-go/deepseek-v4.1-flash` (paid, `OPENCODE_API_KEY` through the credential loader) and
  `opencode/deepseek-v4.1-flash-free` (no login).

The labels are those of `docs/plan/opencode-v2.md`: [V] observed, [I] inferred, [U] needs a run nobody made, [D] vendor
docs. Every [V] below was observed in the raw events and exports of that check, of which this change keeps eight as
fixtures (D8).

IDs: new L4-OCV-015 to L4-OCV-019, SCN-OCV-29 to SCN-OCV-48, change-table row 125. Amended in place: L4-OCV-001, -002,
-003, -004, -005, -006, -007, -008, -009, -011, -012, -013, L4-OCG-002 (the v1 reason's ending), one clause of L4-SEC-005,
L4-FAC-007 (one sentence), the L4-FAC-002 v2 table, the §8.3 v2 row, and SCN-OCV-02, -04, -06, -09, -24 and -26.
L4-OCV-014 (no v2 delegate) is unchanged.

## Decisions

**D1. Pin `@opencode/cli` 2.2.6** (L4-OCV-019; amends L4-OCV-002). The CLI surface from 2.0.32 to 2.2.6 [V, isolated,
no key, both versions]:
- `--standalone` and `--server` moved from the subcommand options to the global flags. `opencode2 run --standalone …`,
  `auth list --standalone --format json` and `session export --standalone <id>`, as `v2_argv` builds them, still
  parse and work.
- `run` gains `--worktree/-w` and `--archived`. L4 passes neither.
- `--pure` and `--dir` are still rejected with exit 1, so L4-OCG-003 still applies to a v2 found as `opencode`.
- `auth list` without `--standalone` hangs on 2.2.6 (2.0.32 answered and left a daemon behind). L4 always passes the
  flag.
- `opencode2 --version` prints `2.2.6`. The probe's `binary` step gates the major only.
- The package installs a platform binary from a postinstall script. With `--ignore-scripts` the bin is a shim that exits
  1 ("postinstall script was not run"). L4's install runs scripts [V], and a shim would fail the `binary` step by name.

`OPENCODE2_VERSION = "2.2.6"`, and with it the install command, `prereqs.sh`'s `OPENCODE2_VERSION` default, the PRQ-20
row of the runner README and every test that names the pin. A test that uses `opencode v2.0.32` as an arbitrary v2
version, or reads a 2.0.32 fixture, keeps it. `tests/fixtures/recorded/opencode/2.0.32/` stays as history: its parser
tests still pass. The live recordings go to `tests/fixtures/recorded/opencode/2.2.6/`, so `recorded_versions.json`
lists `2.0.32` and `2.2.6` under `opencode`, and LIVE-005 compares within major 2 (L4-OCV-012). The pin is in
`catalog_pins`, so `catalog_hash` changes for every consumer: the agent-CLI cache is rebuilt once on upgrade, as with
the 0.4.28 pin.

**D2. Implement-mode permissions are an allow-list** (L4-OCV-015). The 0.4.28 array named the tools L4 wants and left
every other action at OpenCode's default (allow). On 2.0.32 and 2.2.6 an implementer was offered `models`,
`session_move`, `session_rename`, `worktree_create`, `worktree_list`, `worktree_remove`, `list_mcp_resources` and
`read_mcp_resource` (namespace `opencode`, action names `opencode_<tool>`). 2.2.6 also offered `execute` (Code Mode,
which calls `tools.opencode.*` from JavaScript) and `experimental_image_generate`. An implementer created a git worktree
with `worktree_create` on both versions [V mac]: a linked worktree under `$XDG_DATA_HOME/opencode/worktree/<id>/<name>`,
with `.git/worktrees/<name>` in the unit's repository. In the box, the agent sandbox's read-only git common directory
made `worktree_create` and `git worktree add` fail ("Read-only file system") [V box]. So CI is protected by the sandbox
and an unsandboxed run is not.

The implement array now starts with `{"action": "*", "resource": "*", "effect": <refuse>}`, followed by today's rules in
today's order (last match wins):

| Mode | `permissions` (in order) |
|---|---|
| implement | `*:* <refuse>`, `edit:* allow`, `read:* allow`, `glob:* allow`, `grep:* allow`, `shell:* allow`, the git denies (`GIT_WRITES`), the OpenCode CLI denies (D3), `external_directory:* deny`, `external_directory:<result-dir>/** allow`, `external_directory:<result-dir>/* allow`, `webfetch:* deny`, `websearch:* deny`, `question:* deny`, `skill:* <refuse>`, `subagent:* <refuse>` |
| implement with `options.tools` | unchanged: `*:* deny`, the listed tools' allows, the git and CLI denies when `shell` is allowed, then the same tail |
| judge (paid, free) | unchanged |

- `refuse` is `deny` for a paid model and `ask` for an `opencode/` model, the judge's rule (L4-OCV-005). A tool that a
  rule removes from the request gets a 403 from the free tier [V on 2.0.32 for `read` and `shell`]. An `ask` keeps the
  tool in the request, and run mode rejects the call ("cannot ask the user for permission") [V on 2.0.32, rows 10 and
  11; I on 2.2.6, where no free implementer called such a tool]. On a free model, OpenCode's own tools are therefore
  offered and refused at the call. On a paid model they are not offered.
- The tail rules (`external_directory`, `webfetch`, `websearch`, `question`, `skill`, `subagent`) repeat what `*`
  already says. They stay, so the array reads as it did and does not depend on how a later version matches `*`.
- The `options.tools` path keeps its `*:* deny`, including on a free model. That is unchanged, and out of scope.
- Evidence (F1 of the check) [V box]: the implementer was ok on the paid and the free model, and the free judge was ok.
  The paid implementer's tool list was `edit, glob, grep, read, shell, skill, write, opencode_worktree_remove`.
  `execute`, `models`, `session_*`, `worktree_create`, `worktree_list` and `experimental_image_generate` were gone.
- **Residual, stated rather than hidden.** Two tools stay offered:
  - `worktree_remove`: OpenCode gates it with the `edit` action (`permission: "edit"`, which asserts `edit` on the
    directory) [V, binary], and no action rule can remove it while `edit` is allowed. In the agent sandbox it meets the
    same read-only git common directory as `worktree_create` [I: `git worktree add` and `worktree_create` were seen to
    fail; removal needs the same write]. The shell's own `git worktree remove` is not in `GIT_WRITES` either, so this
    tool adds no power the shell lacks.
  - `skill`: offered in every mode, even under a judge's `*:* deny` [V: a bounded judge and a tool-listing judge saw
    `skill` as their only tool]. The one call recorded ended `Unable to load skill read` [V once] and is not a denial.
    The disable switches, the empty config home, the guidance masks and (D4) the private data home leave no skill
    source [I]. U6 stays open.

**D3. The shell may not start the OpenCode CLI** (L4-OCV-016). `opencode2` is on the agent's `PATH`, because the
adapter resolves it there. From the agent's shell, `opencode2 api GET /api/project` and `POST /api/worktree` worked.
Without `--standalone` they start the shared background service (`opencode serve --service`) [V mac and box]. On mac the
service kept running after the run. In the box it died with the sandbox (`--unshare-pid --die-with-parent`) [V].
One sandboxed run was disturbed by it: the agent said the server restarted mid-task, the export holds a `synthetic`
message, and the stream ends with a `step_start` after a `step_finish` of reason `tool-calls`, so it has no final stop.
The export said `succeeded`, and `export_decides` made the run `ok` (SCN-OCV-36).

The denies are `shell:opencode* deny`, `shell:opencode2* deny` and `shell:*bin/opencode* deny`, as `OPENCODE_CLI` in
`opencode_v2.py`. They sit right after the git denies, wherever `shell` is allowed (the default implement array, and
`options.tools` naming `bash`). v2 matches each part of a compound command against a pattern, and `*` spans spaces [V
on 2.0.32: `git add hello.txt && git commit -m add-hello` was refused by `git commit*`].
- The live check used `*/opencode*` as the third pattern. That pattern also refuses any command that names a path
  holding `/opencode`, such as `ruff check src/l4/agents/opencode_v2.py` or `ls tests/fixtures/recorded/opencode` in
  this repository. `*bin/opencode*` refuses an invocation through each install path L4 knows: `~/.local/bin/opencode2`,
  `$L4_HOME/npm-opencode2/node_modules/.bin/opencode2`, the platform package's `bin/opencode` and the curl installer's
  `~/.opencode/bin/opencode` [I: each holds `bin/opencode`]. There is deliberately no `/` before `bin`, because npm's
  `.bin` directory would not match `*/bin/opencode*`. What it may also refuse is harmless: a command naming
  `bin/opencode…` that does not run it, such as `ls ~/.local/bin/opencode2`.
- Evidence (F2 of the check): `opencode2 api GET /api/project` was refused with `Permission denied: shell`, recorded as
  a denial, and the rest of the step went on to an `ok` result [V box, `live-cli-denied`]. The path form was not
  exercised live [I].
- It is a guard, not a boundary. `sh -c '…'`, `env opencode2`, `npx`, a variable or a copy of the binary elsewhere are not
  refused [I]. The sandbox is the boundary: the service dies with the step, and with D4 it sees only the step's own data
  home.
- **v1 does not get these denies.** First, v1 runs in-process and starts no shared daemon (plan row 8), so no ordinary
  subcommand leaves a process behind. `opencode serve` has to be asked for, and inside the sandbox it dies with the
  step. Second, v1's configuration is byte-identical by requirement (L4-OCV-005, SCN-OCV-01), it serves the consumers
  that run v1, and nothing records how v1's matcher treats the path form. Third, the bypass both majors share (a nested
  `opencode run` with a permissive `OPENCODE_CONFIG_CONTENT` of its own) is bounded by the sandbox, not by patterns. A
  later change can add the denies to v1 together with a v1 recording.

**D4. A private data home for a v2 profile that needs no stored login** (L4-OCV-017; amends L4-OCV-003). v2 keeps
`opencode.db` (sessions, messages, credentials), `shell/` (stored shell outputs), `worktree/` and `log/` in
`$XDG_DATA_HOME/opencode`, which L4 never redirected and binds read-write into every opencode step
(`CREDENTIAL_PATHS["opencode"]`). From one sandboxed step, `opencode2 api GET /api/project` listed every earlier step's
project: other repositories, the judge's working directory and the probe's [V box, G3]. A self-hosted runner that serves
several projects accumulates them all. E6 (v2 migrates the runner user's `opencode.db`) has the same root.

- `l4.agents.credentials.no_stored_login(profile)` is true for an `opencode` profile with `options.cli_major: 2` whose
  credential variable is `OPENCODE_API_KEY` (`profile_credential_variable`: `auth: api_key` on `opencode/` or
  `opencode-go/`) or whose model is an `opencode/` model. L4 already treats an `opencode/` model as needing no login:
  its auth step is skipped with `login: not needed`.
- Edge: a paid `opencode/` model reached through a login stored by `opencode2 auth login` under `auth: subscription`
  would get the private home, and its hello would fail as `auth`. The runbook says to use `auth: api_key` with
  `OPENCODE_API_KEY` for it.
- **Run and export.** `XDG_DATA_HOME = <step dir>/opencode2-data`. It is made empty and 0700 by `_fresh_dir` before the
  run (a planted entry is unlinked, never followed) and is not touched before the export, because the session lives in
  that database and the export must read it. Both calls get the same value.
- **Hello.** `XDG_DATA_HOME = <scratch>/data`, an empty 0700 directory in the hello's own scratch directory, which is
  removed after the hello.
- **Auth step.** It never starts `opencode2 auth list` for such a profile [V, code]: `credential_auth` decides for
  `OPENCODE_API_KEY` (set passes, unset fails), and an `opencode/` model is skipped.
- **Not published, not kept.** The step directory is the agent's private temporary directory, apart from the raw
  events, so `publish_agent_logs` never sees the data home. `reset_agent_tmp` removes it before the next step. The agent
  can write it, and the export reads its database: amendment E9.5 (the export never lowers the stream's usage) already
  covers that.
- **The agent's shell inherits the redirect.** `l4.sandbox.home` binds uv's managed Pythons and tools read-only from
  the host's data home (`UV_PYTHON_INSTALL_DIR`, else `<data home>/uv/python`; `UV_TOOL_DIR`, else `<data
  home>/uv/tools`), and uv finds them through `XDG_DATA_HOME` [D]. With the redirect, uv in the agent's shell would look
  in the private directory. So the run and the export of such a profile get `UV_PYTHON_INSTALL_DIR` and `UV_TOOL_DIR`
  set to exactly the directories the sandbox binds, from one helper that `home.py` and the adapter share.
  - Residual [I]: another tool that keeps its data under `XDG_DATA_HOME`, such as a version manager, finds an empty data
    home in such a step. The runbook names it.
- **A profile with a stored login keeps today's data home.** That covers a subscription or OAuth login on `opencode-go/`,
  `openrouter/` and the others: v2 keeps that login in `opencode.db` there.
- **Evidence** (F3 of the check) [V box]: the implementer (paid and free), the judge and the export were ok with the
  private home. Afterwards the step directory held `opencode2-data/opencode/{opencode.db,log,repos,shell}`, and nothing
  new was in the real `~/.local/share/opencode`. The hello with a private data home was not run: the probes of the
  check ran before F3. It is the run form with the judge configuration [I].
- **E6 and U8** no longer apply to such a profile, which never opens the runner user's `opencode.db` in a run, an
  export, a hello or an auth step. They still apply to a v2 profile with a stored login.

**D5. Such a profile's sandbox does not bind the real data and config homes** (L4-OCV-018; one clause of L4-SEC-005).
Decision: yes, for the profiles of D4 only, and for the data and config homes only.
- The process uses its private data home (D4) and its private config home (`XDG_CONFIG_HOME`, since 0.4.28,
  L4-OCV-004). Binding the real ones read-write gives the agent's shell nothing it needs. It does give the shell the
  sessions of other runs (G3), a v1 login's `auth.json` in the same directory, and a writable config home where a
  planted plugin or `opencode.json` waits for the next OpenCode process that reads it (E9).
- `~/.cache/opencode` stays bound. `XDG_CACHE_HOME` is not redirected and the process uses it: it created
  `opencode/bin` there [V mac]. Hiding it was not tried.
- **Mechanism.** `SandboxSpec.hide_own_homes: bool` is keyword-only and defaults to False. `l4.sandbox.base.OWN_HOMES`
  is `{"opencode": ("~/.local/share/opencode", "~/.config/opencode")}`. `own_login_binds(spec)` returns the spec's own
  credential paths, configured or built in. When `hide_own_homes` is set, it drops each path that is, contains or lies
  inside one of the adapter's `OWN_HOMES` (expanded against `spec.home`), which fails closed for an odd configured path.
  `hidden_credential_paths(spec)` adds the dropped paths, so they are covered by a tmpfs or `/dev/null` like any other
  hidden login. `BwrapSandbox.build_argv` binds `own_login_binds(spec)`.
- **Where the flag is set.** `Workbench.agent_spec` and the readiness review's spec (`yolo/readiness.py`, the other
  place that builds an agent spec for a profile) set it from `no_stored_login(selected.profile)`. The sandbox doctor
  check, the dry run and `scripts/runner/sandbox-probe.sh` build specs without a profile and keep the default.
  `test_probe_parity.py` passes unchanged. `sandbox: none` hides nothing, as today.
- **v1 is unchanged, and a test proves it.** For a `cli_major: 1` profile with `auth: api_key` on
  `opencode-go/deepseek-v4.1-flash`, one with a subscription, and a `cli_major: 2` profile on `openrouter/…` (a stored
  login), the bwrap argv built through `agent_spec` equals, element for element, the argv of the same spec with the
  field left at its default. All three opencode login paths stay `--bind` (SCN-OCV-41). No recording shows that a v1
  api-key run needs none of them, so v1 keeps them.

**D6. Supported, not experimental** (L4-OCV-019; amends L4-OCV-001 and L4-OCV-013). What was checked live on the pinned
version, in L4's real sandbox:

| Path | mac | box (bwrap) |
|---|---|---|
| probe ladder `binary`, `auth`, `quota`, `hello` on `opencode-go/` (api key) | ok (hello 2.0 s) | ok (hello 6.2 s) |
| probe ladder on an `opencode/` free model (no login; auth skipped) | — | ok (hello 1.9 s) |
| judge: the schema reply in the last message, paid and free | ok | ok |
| implementer: edit, result file, export, usage; paid and free | ok | ok |
| the allow-list (D2), the CLI deny (D3), the private data home (D4) | — | ok |
| `options.steps.judge: 2`: the bound | `step_bound` error | — |
| `options.tools: [read, edit]`: no shell tool in the request | ok | — |
| processes left after a normal run | none | none |

- **Removed:** `experimental = True` (no `agent.experimental` event), the experimental wording of L4-OCV-001, L4-OCV-013,
  the §8.3 row, the CHANGELOG (an Unreleased line; released lines keep their text), the runbook section and the
  plan, and the v1 gate reason's `(experimental)` (L4-OCG-002, `catalog.MAJOR_WORDS["opencode"]`).
- **L4-NFR-006 still holds.** Every remaining [U] row ships with a fallback that a contract test pins by name (L4-OCV-013).
  The `codex` and `claude-code` adapters are held to the same standard and are not experimental. Their §8.3 rows keep
  unrecorded facts on pinned behaviour: codex's usage-limit `turn.failed` shape, "U, not reproduced", and claude-code's
  full schema form, "U — pinned by a contract test". `kiro-cli` and `copilot-cli` are still experimental, for reasons of
  their own.

**D7. The live check and the deferred B8 and B9 of `opencode-v2`.** The check replaces B8 for the rows it recorded. It
ran on a local Linux container with L4's real bubblewrap sandbox, and on macOS without one. It ran on no CI runner and
no runner that serves a consumer, so E6 held.
- B8.1, a dummy repository with `l4 doctor --ci --fix`: not done. The container installed `opencode2` the way the
  catalog does.
- B8.2: done for U5 (the census below), U7, U11 and the bounded judge. U9 was done in part: no leak in 24 runs, and
  `steps: 1` was not run.
- B8.3 (U1), B8.5 (U3), B8.6 (U4), B8.7 (U6, the canary) and B8.8 (U8): not done. U8 is moot for D4's profiles.
- B8.4 (U2): done.
- B8.9: the fixture task of this change.
- B9.1 is satisfied without code: every recording matched its fallback (D9). The pin tests are re-pointed at the live
  fixtures and the [U] becomes [V].
- B9.2: done by D6 with rows still open, by the owner's decision. The open rows are listed as known fallbacks.
- **Not covered, and not claimed:** row 68's "a unit on the owner's dummy repository runs end to end with a v2
  implementer and a v2 free judge". The check drove `OpenCodeV2Adapter.probe` and `run` directly, which is the
  adapter's whole contract with the harness. Everything above it (orchestrator, ladder, verifier) is adapter-agnostic
  and covered with the other adapters, but no full L4 unit has run on v2.

The U5 census on 2.2.6 counts 24 runs: 12 on mac and 12 in the box, from 1 to 23 steps. Twenty-two ended with a final
`step_finish` of reason `stop`. One ended on an `error` event with no step (a free model with no route). One lost its
final stop after the agent's shell started the CLI (`live-cli-disturbed`). On 2.0.32, 13 of 16 finished runs had
lacked it. So `export_decides` stays.

**D8. Fixtures** (task 7). The orchestrator passes the two raw directories of the check as `OC2_MAC` (the mac runs) and
`OC2_BOX` (the box runs). Each source is `<dir>/<run>/step/events.jsonl` and `<dir>/<run>/step/events.export.json`. Each
target is `tests/fixtures/recorded/opencode/2.2.6/live-<name>.jsonl` and `live-<name>.export.json`:

| Source run | `<name>` | What it holds |
|---|---|---|
| `$OC2_BOX/judge-1` | `judge` | a paid judge in the sandbox: one step, the JSON reply, `succeeded` |
| `$OC2_BOX/judge-4` | `judge-free` | a free judge (`opencode/deepseek-v4.1-flash-free`) in the sandbox with the private data home |
| `$OC2_BOX/implement-3` | `implement` | a paid implementer in the sandbox with the allow-list and the private data home: `read`, `edit`, `write` in 4 steps, one assistant message per step |
| `$OC2_MAC/bounded-1` | `bounded` | a judge with `options.steps.judge: 2`: a `skill` call that found no skill, the forced summary step, outcome `succeeded` |
| `$OC2_MAC/tools-1` | `tools-permission` | `options.tools: [read, edit]` and a prompt asking for a shell command: no `shell` tool, the model said so |
| `$OC2_BOX/daemon-2` | `cli-denied` | the allow-list, the CLI denies and the private data home: `opencode2 api GET /api/project` refused, the step went on |
| `$OC2_BOX/daemon-1` | `cli-disturbed` | no CLI deny: the shell ran `opencode2 api …` (the listing of earlier steps' projects, G3), the stream lost its final stop, the export has a `synthetic` message |
| `$OC2_BOX/judge-2` | `error-no-route` | a free model with no route: one `error` event `provider.no-route` without `status`, exit 1, outcome `failed` |

- The task brief named a paid hello. No raw stream of a hello was kept: the probe ran in a temporary directory, and
  only its verdict is in the check's report. The README records the probe verdicts as LIVE checks without a fixture.
- **Scrub rules**, in the manner of the 2.0.32 README:
  - every path under the mac runs' directory (`$OC2_MAC`, with or without the `/private` prefix) becomes `/tmp/l4-oc2/`
    plus the rest of the path;
  - a remaining `/private/tmp/` prefix, or a `/tmp/` prefix other than `/tmp/l4-oc2`, that the model shortened with `…`
    becomes `/tmp/l4-oc2/`;
  - `/home/runner` becomes `/tmp/l4-oc2box`, and a path that starts with `/out/` becomes `/tmp/l4-oc2box/out/`;
  - each `ses_…` id becomes `ses_l4live<n>`, one per run, the same in the stream and its export;
  - any remaining occurrence of the recording user's login becomes `user`.
- Message and part ids, project hashes and timestamps stay. No source file holds a key or an `API_KEY` assignment [V,
  checked].
- The verified parse results (status, detail, denials, usage) of each file are in SCN-OCV-32, -35, -36, -44, -45, -46
  and -47. The current parser was run on the raw files to get them.

**D9. The [U] rows after this change** (L4-OCV-013):

| # | Fact | 2.2.6 | Fallback | Pinned by |
|---|---|---|---|---|
| U1 | the 402 and 429 shapes, `retry-after` | open | `status_only` | synthetic test (as before) |
| U2 | a v2 deny drops the tool's schema | [V] the denied tool is not offered | `tools_by_permission` (kept: it was right) | `live-tools-permission` |
| U3 | the custom provider's `{file:}` key | open | `provider_refused` | load test (as before) |
| U4 | the OAuth refresh failure text | open | `auth_by_status` | synthetic test (as before) |
| U5 | how often the final `step_finish` is missing | [V] 1 of 23 finished runs, a disturbed one | `export_decides` (kept) | `live-cli-disturbed` |
| U6 | guidance isolation in a real prompt | open; `skill` is offered and a call loaded nothing [V once] | `deny_skill_and_mask` | as before |
| U7 | outcomes other than `succeeded`; a bounded run's outcome | [V] `failed` after an `error` event; a bounded run says `succeeded`; others open | `not_ok_named` (kept: the bound decides first) | `live-bounded`, `live-error-no-route` |
| U8 | v1 and v2 sharing one `opencode.db` | moot for D4's profiles; open for a stored login | `live_coexistence` | none (an operator rule) |
| U9 | the `</think>` cause; `steps: 1` | in part: 0 leaks in 24 runs; `steps: 2` makes step 2 the summary [V]; `steps: 1` open | `strip_leading_think`, judge floor 2 | as before, plus `live-bounded` |
| U10 | SIGINT's exit code | open | `harness_interrupt` | as before |
| U11 | a multi-step export's layout | [V] one assistant message per finished step, summing to `info.tokens` in all 23 exports | `sum_messages` (kept) | `live-implement`, `live-cli-disturbed` |

A new [V] shape (`live-error-no-route`): an `error` event `{type: "provider.no-route", message: "Model unavailable:
…"}` with no `status`. Today's rule makes it `error … (provider.no-route), retryable`, through the server-side word
`unavailable`. It is pinned as is. No new parser is written.

## Risks

- **The allow-list may refuse a tool a later OpenCode moves under a new action.** That is the intent. Such a tool shows as a
  denial or a missing tool, never as a silent allow. If a core tool (`edit`, `write`) moves, the implementer's step
  fails visibly, and the pin is exact (LIVE-005 warns on a patch drift).
- **The CLI deny is a pattern guard** (D3). The sandbox is the boundary. A run with `sandbox: none` (a person's macOS)
  keeps the daemon risk for an invocation the patterns miss.
- **The private data home moves `XDG_DATA_HOME` for the whole agent process tree** (D4). uv is handled. A tool that
  finds its data through `XDG_DATA_HOME` and is not uv sees an empty data home [I]. Every step also starts a fresh
  `opencode.db`. Its creation cost was not measured on its own [U]. Sessions with the private home took 1.3 to 7.9 s,
  in the same range as those without it (1.3 to 54.9 s) [V box, export `info.time`].
- **`worktree_remove` and `skill` stay offered** (D2). Both are covered by the sandbox and the isolation, and stated in
  the SPEC and the runbook.
- **No full L4 unit has run on v2** (D7). The first consumer unit on a v2 profile is the first end-to-end evidence. The
  runbook says to watch its first `verification.md`.
- **v2 moves fast** (2.0.32 to 2.2.6 in three weeks). The pin is exact, and a move is a re-check of D1's surface list
  plus a recording.
