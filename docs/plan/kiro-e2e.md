# Kiro end-to-end SDD validation plan (2026-10-07)

Goal: prove, with evidence, that a feature specified **by Kiro** (requirements → design → tasks) goes through the
harness end to end with **kiro-cli as the only implementer**: intake, red/green TDD, independent verification,
hand-off, human merge, done-gate and archive, with Kiro's own conventions (markers, optional tasks, waves,
`_Requirements:_`, steering) respected. Two venues: **H1** this Mac with the in-memory forge, **H2** live on
dummy-agentic (GitLab 118) through CI on the shared runner.

Labels: **[V]** observed this session (command output, file, code read), **[I]** inferred, **[U]** not checked,
**[D]** from Kiro's docs only. Step 0 and venues H1 and H2 have run since: results in
[../live/kiro-e2e/README.md](../live/kiro-e2e/README.md) (H2, 2026-10-08: works end to end, with caveats).

## 0. Verdict before any run

* kiro-cli 2.28.0 works headless on this Mac with a browser login [V]. The runner's CI user `gitlab-runner` **is now
  logged in** (AWS Builder ID, `KIRO FREE`, 0.00 of 50 credits used) [V, 2026-10-07 ~22:30Z]; the task's "not logged in"
  fact is stale.
* **The harness cannot use either login today.** Its auth probe expects `whoami --format json` to hold an `account`
  object; both 2.28.0 and 2.27.1 print a flat object, so the probe answers "unrecognised answer" and every chain skips
  Kiro [V: the harness's own `probe_kiro` run against the real CLI]. Gap K1, a blocker for both venues.
* **Security, now live on the runner:** the Kiro token store `~/.local/share/kiro-cli` is in no adapter's
  `CREDENTIAL_PATHS`, so under bubblewrap (`--ro-bind / /`) every agent and gate sandbox of any project on the runner
  can read `gitlab-runner`'s Kiro token, and Kiro itself gets it read-only (gap K2). Fix it before the next CI run that
  could execute agent-written code, independent of this plan.
* So step 0 (harness changes, test-first, then the vendored upgrade on the dummy) comes before H1 and H2.

## 1. kiro-cli 2.28 capability facts

| # | Fact | Label / source |
|---|---|---|
| C1 | Versions: Mac `~/.local/bin/kiro-cli` 2.28.0; runner `admin` 2.28.0; runner `gitlab-runner` **2.27.1** | [V] |
| C2 | Accounts: Mac = Google social login, **`KIRO PRO`, 1000 credits/month** (not free); runner `admin` = Google social; runner `gitlab-runner` = **Builder ID, `KIRO FREE`, 50 credits**, reset 2026-11-01 | [V `/usage`, `whoami`] |
| C3 | Headless: `kiro-cli chat --no-interactive [--agent NAME] [--model M] [--trust-tools=LIST \| --trust-all-tools] --output-format stream-json "<prompt>"`. Works with a browser/device login; the docs say headless needs `KIRO_API_KEY` (Pro+ only), which is wrong for 2.28 | [V], docs https://kiro.dev/docs/cli/headless/ [D] |
| C4 | `--output-format stream-json` = ACP-shaped JSON lines: `runStarted{payloadSchema:"acp", engine:"v2"}`, `metadata{sessionId, contextUsagePercentage, meteringUsage:[{value, unit:"credit"}], turnDurationMs}`, `sessionUpdate{update:{sessionUpdate: agent_message_chunk \| tool_call \| tool_call_update, _meta.kiro.toolName, status}}`, `runFinished{status, stopReason, finalText, finalTextTruncated}`, `runError{stage, message}`. No served-model field | [V] |
| C5 | Exit codes: 0 success (also when every tool call was denied and the model just says "DONE"), 1 failure, 3 MCP startup failure under `--require-mcp-startup`, 4 requested agent not found (`runError{stage:"init"}`, before any model call) | [V 0, 4], https://kiro.dev/docs/reference/exit-codes/ [D 1, 3] |
| C6 | Tool names are `read`, `write`, `shell`, `glob`, `grep`, … (`_meta.kiro.toolName`; agent example). On the **default agent** `--trust-tools=read,write,shell` and the old `fs_read,fs_write,execute_bash` both trust native write and shell (aliases work) | [V] |
| C7 | `--trust-tools=` (empty) **trusts everything**: a shell `date > d.txt` ran with it, on the default agent and on a custom agent whose `allowedTools` was `["read"]`. `--trust-tools=read` denies shell (`[denied] tool permission approval is not supported in non-interactive mode` on stderr) | [V] |
| C8 | Under a **custom agent** a non-empty `--trust-tools` list is ignored: `read,write,shell` and `fs_*` were both denied; `--trust-all-tools` works. Whether the agent's `allowedTools` grants trust is [U] | [V] / [U] |
| C9 | The user-level `~/.kiro/settings/permissions.yaml` (v3 capability rules) auto-approves matching shell commands whatever `--trust-tools` says (`echo hi > a.txt && ls` ran under a list without shell trust on the Mac, whose file allows `echo *`, `ls *`) | [V Mac]; https://kiro.dev/docs/cli/v3/ [D] |
| C10 | Agents: `--agent` takes a **name** only (a path gives "Mode … not found", exit 4); names resolve from `<cwd>/.kiro/agents/` and `~/.kiro/agents/`. A workspace agent with `includeMcpJson: false, mcpServers: {}, tools: [read, write, shell]` exposes 3 tools; the default agent exposes 42 on this Mac (user MCP servers `context7`, `git`, `filesystem` from `~/.kiro/settings/mcp.json`, plus 31 user skills in `~/.kiro/skills`) | [V] |
| C11 | Cost: a one-turn hello on `qwen3-coder-next` cost 0.028 credits with the default agent and 0.0105 per turn with the 3-tool agent (the user MCP/skill context costs ~2.7x) | [V meteringUsage] |
| C12 | Models (rate multiplier). Runner FREE: `auto` 1.0, `claude-sonnet-4.5` 1.3, `claude-sonnet-4` 1.3 (EOL 2026-10-14), `claude-haiku-4.5` 0.4, `deepseek-3.2` 0.25, `minimax-m2.5` 0.25, `minimax-m2.1` 0.15, `glm-5` 0.5, `qwen3-coder-next` 0.05. The Mac PRO list adds `claude-opus-5.5/5/4.x`, `claude-sonnet-5.5/5/4.6`, `gpt-5.6-sol/terra/luna`. Default model `auto` (Kiro picks; vendor unknowable) | [V `chat --list-models --format json`] |
| C13 | `/usage` runs headless with no model call: `Credits (X of N covered in plan)` and the plan name | [V both hosts] |
| C14 | Spec authoring: in the CLI it is the v3 engine's `/spec new <name>` (Feature requirements-first / design-first, Bugfix, or **Quick Spec** = no approval gates) with phase checkpoints in the TUI, and `/spec run <name>` for the task runner. The docs and a 2.8.0 field report say v3 is TUI-only. On 2.28.0, `kiro-cli chat --no-interactive --v3 --mode spec "Reply with exactly: L4-OK"` started KAS 0.66.26 and answered (exit 0); whether a full spec is authored headless is [U] | [V hello], https://kiro.dev/docs/specs/ , https://kiro.dev/docs/cli/v3/ , https://dev.classmethod.jp/articles/kiro-cli-v3-quick-spec-early-access/ [D] |
| C15 | Steering: `.kiro/steering/*.md` (workspace), `~/.kiro/steering/` (global), `AGENTS.md`; front matter `inclusion: always` (default) \| `fileMatch` + `fileMatchPattern` \| `manual` \| `auto`. The default agent includes steering; a custom agent only through `resources: ["file://.kiro/steering/**/*.md"]` | https://kiro.dev/docs/steering/ [D] |
| C16 | MCP: `kiro-cli mcp add/remove/list/import/status`; workspace `.kiro/settings/mcp.json`, global `~/.kiro/settings/mcp.json`, per-agent `mcpServers`; `--require-mcp-startup` turns a failed server into exit 3 | [V help], [D] |
| C17 | Login storage: the token is in the CLI data store, not `~/.kiro`: macOS `~/Library/Application Support/kiro-cli/data.sqlite3` table `auth_kv` key `kirocli:social:token` [V names only]; Linux `~/.local/share/kiro-cli/data.sqlite3` (present for `admin` and `gitlab-runner`) [V dir, I contents] | |
| C18 | Startup latency: 15 to 38 s per call on the Mac with the user MCP servers starting | [V] |

Probes run (all in the scratchpad `kiro-probe/`, ~0.25 credits of the Mac's PRO plan): one hello, five
trust/tool-name probes, one v3 spec-mode hello, one missing-agent probe. On the runner: read-only file listings,
`whoami --format json` key shapes, `chat --list-models` and `/usage` as `gitlab-runner` (no model call; this did write
CLI session state in `gitlab-runner`'s store). No credential was copied or moved.

## 2. Gap list (harness vs kiro-cli 2.28 and Kiro's conventions)

Severity: **blocker** (the e2e cannot pass), **high**, **medium**, **low**.

| ID | Sev | File | Finding | Fix sketch |
|---|---|---|---|---|
| K1 | blocker | `src/l4/agents/kiro_cli.py` (`probe_kiro`), `tests/unit/availability/test_probes_kiro.py` | Auth reads `answer["account"]`; logged-in 2.28.0 prints `{"accountType":"SocialGoogle","email":…}`, 2.27.1 Builder ID prints `{accountType, email, region, startUrl}` → "kiro-cli whoami gave an unrecognised answer" [V live]. The test's logged-in fixture encodes the guessed shape | Logged in iff exit 0 and a non-empty `accountType` (keep only `accountType`; never `email`/`startUrl`); logged out stays exit 1 / `{"account": null}`. Record redacted fixtures `kiro-cli/2.28.0/mac-whoami-social` and `2.27.1/runner-whoami-builderid` first (red), then fix |
| K2 | blocker (H2), security | `src/l4/config/defaults.py:56` `CREDENTIAL_PATHS["kiro-cli"] = ("~/.kiro", "~/.aws/sso/cache")` | The token store `~/.local/share/kiro-cli` is not listed, so (a) bwrap shows it to every other agent and gate via the read-only root (not in `hidden_credential_paths`), and (b) Kiro itself sees it read-only (token refresh and sqlite writes fail [I]). Live since `gitlab-runner` logged in | Add `~/.local/share/kiro-cli` and `~/Library/Application Support/kiro-cli`; a test in the bwrap suite that a codex spawn and a gate spawn hide it and a kiro spawn binds it rw; SPEC 3.2 + L4-SEC-005; free-resources section 8/9 |
| K3 | high | `kiro_cli.py` `build_command`; SPEC 8.3 / the "explicit harness agent" claims (SPEC lines ~1381, ~2640) | No harness agent: the default agent loads the user's MCP servers, skills, global steering and `AGENTS.md` (42 tools vs 3 [V]); with `--require-mcp-startup` a cold `npx` user server makes a spurious exit 3. `--agent` takes a name only [V]; the worktree `.kiro/agents` is protected and tmpfs-masked | Generate `l4-<step>.json` (`includeMcpJson:false`, `mcpServers:{}`, `tools:[read,write,shell,glob,grep]`, `allowedTools` per policy, `resources:[]` or steering, see K10). Under bwrap `--ro-bind` it to `<wt>/.kiro/agents/l4.json` after the masks; under `sandbox.mode: none` write a run-scoped `~/.kiro/agents/l4-<step>.json` and remove it after [I]. First probe C8: does `allowedTools` grant trust headless [U] |
| K4 | high | `kiro_cli.py` `TRUST_TOOLS["judge"] = ""` | `--trust-tools=` trusts everything (C7) | Judge: harness agent with `tools: []` (or `--trust-tools=read` in the empty judge dir until K3). Unreachable today (Kiro is not in `JUDGE_ADAPTERS`), but the policy string means the opposite of what it says **Done (kiro-judge, 0.4.19):** `TRUST_TOOLS` has no judge entry; a judge runs the tool-less harness agent with no trust flag (L4-KJD-001). |
| K5 | high | `defaults.py:56` (`~/.kiro` as a credential path) | `~/.kiro` holds no credential but is bound read-write into the Kiro sandbox: user `settings/mcp.json`, `settings/permissions.yaml` (auto-approves shell, C9), `agents`, `steering`, `skills` leak into runs, and an implementer can write them to influence later units [I] | Bind only the data dir (K2) plus a harness-made minimal `~/.kiro` (tmpfs + the generated agent); doctor warns when `permissions.yaml` exists for the runner user |
| K6 | high (D) | dummy `.l4/config.yaml` profile `kiro`; SPEC 3.2 example (`vendor: amazon`, `auth: api_key`) | No `model` → `auto` → vendor unknowable (vetoes every judge); `amazon` is wrong. With any `claude-*` model the Claude judge is **not** independent and the verdict drops to a free judge. `TOOL_VENDORS` has no `kiro-cli` entry, so a declared vendor is accepted [V] | Config: `model: qwen3-coder-next`, `vendor: alibaba` (alternatives: `deepseek-3.2`/deepseek, `glm-5`/zhipu, `minimax-m2.5`/minimax). Doctor: a `kiro-cli` profile without `model` is "vendor unknown". Fix the SPEC example |
| K7 | high (FREE tier) | `kiro_cli.py` `parse`, `probe_kiro` quota/hello | The stream is not parsed: credits, session id, final text and limit messages are lost; out-of-credits is `error` (a failed attempt toward the halt), not `quota` (cool-down + fallback). Quota and hello are skipped though `/usage` and `runFinished.finalText` exist (C4, C13). What Kiro prints when credits run out is [U] | Parse C4 events; `usage` from `meteringUsage`; `session_id`; classify `runError`/stderr credit and auth text; quota probe = `/usage` ratio vs `min_remaining_percent`; hello = `runFinished.finalText`. Record the out-of-credits text when it first happens |
| K8 | medium | `kiro_cli.py` `parse` | Exit 4 (agent not found) and `runError{stage:"init"}` count as a failed attempt; they are configuration errors | Map to an unavailable/config failure that falls back, with the `runError.message` as detail (after the e2e: G2 uses exit 4, step 0c) |
| K9 | medium | `src/l4/specs/kiro.py` (`set_marker` writes `x` only), `src/l4/orchestrator.py:1064` | `spec.kiro.write_in_progress_marker` (default **true**) and `write_queued_marker` are ignored with an info log, while SPEC 3.2 says `[-]` is written while a task runs. Kiro and the maintainer's skill write `[ ]`→`[~]` queued →`[-]` started →`[x]` | Either implement one-byte `-` (at red start, in the red commit) and `~` (planned leaves, reset on stop/halt), or set the default to false and fix the SPEC. The M1.4 byte census (4 bytes, size unchanged) shows the `x` path is right |
| K10 | medium | prompt builders; `sandbox/base.py` masks `.kiro/steering` | Steering is neither loaded (masked under bwrap, by design L4-SEC-002) nor injected, so a Kiro repo's project rules reach no implementer in CI, but do reach Kiro on a sandbox-less venue (C15): venue-dependent behaviour | Inject member-written steering (`always`, and `fileMatch` against the task's files) as a trusted section, inside the prompt hash; for Kiro also as agent `resources` (K3) |
| K11 | medium | `src/l4/specs/criteria.py:108-109` | Requirements must be `### Requirement N` and `#### Acceptance Criteria`; the skill accepts heading levels 2–4 (mintkey-mvp uses `## Requirement N`); the v3 spec format is not recorded [U] | Accept levels 2–4; keep a v3-authored spec from step A as a golden fixture |
| K12 | low | `kiro.py` `_REQUIREMENTS` | Only `_Requirements: …_` is a link. If Kiro's property-test tasks cite `**Validates: Requirements X.Y**` [I/U], a required leaf with only that form fails SPEC-004 under `sdd.enforce` | Check the step A output; if present, read that form too |
| K13 | low | `src/l4/llm/agent_judge.py:30` | Kiro can neither judge nor clarify; now feasible (`runFinished.finalText`, C4) once K3/K4/K7 land | Add `kiro-cli` to `JUDGE_ADAPTERS` behind a tool-less harness agent and a recorded judge run **Done (kiro-judge, 0.4.19):** `kiro-cli` is in `JUDGE_ADAPTERS` and serves the judges, the clarifier, the readiness review and the `s1_judge` stand-in (L4-KJD-008); the live proof is task 11.1 of the change. |
| K14 | low | `kiro.py` waves | Divergences by design (SPEC L4-KSP-002): waves only order a serial run; an invalid graph rejects intake (exit 14) where Kiro falls back to sequential; a pending leaf missing from the graph keeps its document position (Kiro appends it); no `--include-optional` | Document; no change |
| K15 | low | `kiro.py` `Task.started` | A `[-]`/`[~]` left by a Kiro IDE run is re-implemented as pending; the skill reviews such work first | Optional: a "review existing" step for `started` leaves |
| K16 | low | `src/l4/memory/serena.py:43`, `memory/inject.py` | `_CONTEXT_BY_ADAPTER` keys `"kiro"`; the adapter is `"kiro-cli"` (moot: the adapter takes no MCP). L4-MEM-003's "Kiro agent `resources`" lessons channel is not implemented | Rename the key; implement with K3 or drop from the SPEC. **Assessed 2026-10-24, no change:** K3's harness agents (implementer, judge, delegate) carry `"mcpServers": {}`, so renaming the key would start a Serena check for a run that cannot use Serena; the `"kiro"` entry is dead and goes when `serena.py` is next touched. L4-MEM-004 now says a `kiro-cli` run starts no MCP server. Giving Kiro Serena is a feature (Serena in the K3 agent file, a live run) |
| K17 | low | SPEC 8.3 row, `kiro_cli.py` docstring, free-resources rows, test fixtures | Several [U] items are now [V] (C3–C8, C13); version text says 2.27.1 logged out; fixtures pin `claude-sonnet-4` (EOL 2026-10-14); the Mac account is PRO, not free | Update after step 0 |
| K18 | low | `kiro_cli.py` `MAX_ARG_BYTES` | The prompt is one argv entry (≤100 KB, visible in `ps` to same-user processes); stdin is accepted per the docs [D, untested] | Test stdin once; switch if it works |

Kiro conventions that the harness already matches [V code + M1.4 live]: task grammar regex verbatim; optional `*`
right after `]` (also inherited by children); hierarchy by dotted number, else indentation; leaves only executed;
parents closed when all required children are done (one byte each); done-gate over required leaves; `_Requirements:_`
links with a dangling ref as an intake ERROR; the `## Task Dependency Graph` JSON read for wave order; byte-exact one-byte
`x` writes; implementer prompt reaches Kiro as one argv entry; the result comes back through the M1.13 alias
`.l4-result/result.json` (a symlink into the step's private directory, `RESULT_ALIAS_PATH` for every
`prompt_contract` adapter) and is read only from the private directory.

## 3. The feature under test

Unit `kiro:add-bulk-discount` on dummy-agentic (nothing about bulk discounts exists today [V grep]): a line item whose
quantity is at least 10 gets 5 percent off its line total; `Cart.bulk_savings()` returns the cart's total saving.
Two required leaves, one optional property-test leaf, a graph whose wave order differs from document order (so wave
handling is observable), and a steering rule that only steering states (so F5 is observable).

Authoring brief (the text given to Kiro in step A; `$BRIEF` below):

> Create a Kiro feature spec named `add-bulk-discount` in `.kiro/specs/add-bulk-discount/` for this repository (a
> Python pricing library; `src/pricing/cart.py` has `LineItem` and `Cart`). Feature: a line item whose quantity is at
> least 10 gets 5 percent off its line total, money rounded half-up to 0.01; `Cart.bulk_savings()` returns the sum of
> the savings of its line items. Write exactly three files in Kiro's spec format. `requirements.md`: `# Requirements
> Document`, `## Introduction`, `## Requirements`, then for each requirement `### Requirement N`, a `**User Story:**`
> line and `#### Acceptance Criteria` with a numbered list of EARS criteria (`WHEN … THEN the system SHALL …`) covering
> quantity 10 and 9, rounding, and an empty cart. `design.md`: Overview, Architecture, Components and Interfaces, Data
> Models, Error Handling, Testing Strategy, Correctness Properties. `tasks.md`: `# Implementation Plan`, numbered
> checkbox tasks `- [ ] N. Title` with sub-tasks `  - [ ] N.M Title`, each leaf followed by an indented
> `- _Requirements: X.Y, …_` line; one optional property-test sub-task written `- [ ]* N.M`; task 1 is the cart method
> and task 2 the bulk rule module; end with `## Task Dependency Graph` and a fenced json block
> `{"waves": [{"id": 0, "tasks": [<task 2 leaves>]}, {"id": 1, "tasks": [<task 1 leaves>]}]}`. Do not write code or
> tests and do not change any other file.

Steering seed (a separate human commit **after** A, so the spec cannot carry the rule), `.kiro/steering/pricing-rules.md`:

```markdown
---
inclusion: always
---
# Pricing code rules
- Every new module-level constant in `src/pricing/` is listed in `__all__` of `src/pricing/__init__.py`.
- Every new public function's docstring ends with the requirement numbers it implements, for example `(Req 1.1, 1.2)`.
```

## 4. Step 0: harness changes and runner readiness (before either venue)

All harness work test-first in `/Users/USER/src/l4`, local commits by path
as CiprianSpot, no trailers, never pushed; long suites in background mode; never `pytest | tail` in an `&&` chain.

| Step | Do | Evidence |
|---|---|---|
| 0a | K1 (red: the two recorded whoami shapes fail; green: accepted, `detail == {"logged_in": True, "account_type": …}`, no e-mail) | red/green commits; `uv run python <scratch>/kiro-probe/probe_live.py <dir>` prints `auth True` on the Mac |
| 0b | K2 (bwrap argv tests: kiro binds `~/.local/share/kiro-cli` rw; codex, claude-code, opencode and gate spawns hide it) | red/green commits |
| 0c | K4 (small): the judge trust string. **K8 is deferred until after the e2e**: G2 uses exit 4 as its zero-credit, deterministic halt trigger, which K8 would turn into a fallback | red/green commits |
| 0d | Recommended before H1, required before treating H1's isolation as clean: K3 (harness agent; probe C8 first, ~0.02 credits) and K5 | commits; one recorded `stream-json` run whose `tool_call` events show only `read`/`write`/`shell`/`glob`/`grep` |
| 0e | Recommended before H2 (50-credit plan): K7 (stream parsing, `/usage` quota, credit/limit classification) | commits; recorded fixture from C4 |
| 0f | Full suite in the background; `l4 simulate --all` green (`happy-kiro` included) | suite + simulate output |
| 0g | Runner, read-only: `uv run --no-project python scripts/dev/l4_idle.py`, then `scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh` (check mode; expect PRQ-12 `kiro-cli 2.27.1`, PRQ-15 `auth: kiro-cli logged in`). Optional runner change, only through a test-first `prereqs.sh` extension: a Kiro version floor (2.28.0) for `gitlab-runner`, since C6–C8 were measured on 2.28.0 | `docs/runner/prereqs-<date>-kiro-check.txt` |

## 5. Venue H1: this Mac, local forge

Variables: `H=/Users/USER/src/l4`,
`S=/tmp/scratch/kiro-e2e`,
`K=~/.local/bin/kiro-cli`, `L4="uv run --frozen --project $H l4"`, `U=kiro:add-bulk-discount`,
`export L4_CACHE=$S/h1-cache` (never the default `~/.cache/l4`). `$S` is the session scratchpad that the 2026-10-07
workflow fixed for the clones; a later session substitutes its own directory.

**Setup**

1. `git -C $S/dummy pull --ff-only && git clone --bare $S/dummy $S/h1-origin.git && git clone $S/h1-origin.git $S/h1`
   (a local bare origin: no GitLab write is possible). `git -C $S/h1 config user.name CiprianSpot; git -C $S/h1 config user.email maintainer@example.invalid`.
2. `$S/h1-cfg.yaml` = the dummy's `.l4/config.yaml` with: `harness.commit: <H HEAD>`; `forge.type: local`;
   `ci.platform: local`; `sandbox: {mode: none, allow_none: true}` (macOS has no bubblewrap [V `bwrap` missing]; the
   only option, and a recorded risk acceptance: agents run as this user); `gates.e2e` removed and
   `verifier.playwright.enabled: false` (no UI change in this unit); `memory.serena.enabled: false`;
   `verifier.s1.enabled: false`, `s1_judge: []`; `verifier.max_fix_rounds: 0`; `audit_sample_ratio: 0`; profiles
   ```yaml
   kiro-qwen:    {adapter: kiro-cli, model: qwen3-coder-next, vendor: alibaba, auth: subscription}
   kiro-unavail: {adapter: kiro-cli, model: qwen3-coder-next, vendor: alibaba, auth: subscription, min_version: "99.0.0"}
   kiro-halt:    {adapter: kiro-cli, model: qwen3-coder-next, vendor: alibaba, auth: subscription, options: {agent: l4-does-not-exist}}
   ```
   and roles `judges: [claude-code]`, `verifier_agent: [claude-code]`, `clarifier: [f-longcat, claude-code]`
   (codex is not installed here [V]); `implementer` is set per step below.
3. Credits before: `(cd $S && $K chat --no-interactive --trust-tools=read "/usage") > $S/h1-evidence/usage-before.txt`.

**A. Authoring by Kiro** (in `$S/h1`, on a scratch branch `kiro-e2e/author`; model `claude-sonnet-4.5`, authoring is
not implementing so its vendor does not enter the independence check; budget ≤ 20 PRO credits [I])

* A1 headless spec mode (C14 [U]):
  `cd $S/h1 && timeout 900 $K chat --no-interactive --v3 --mode spec --model claude-sonnet-4.5 --trust-tools=read,write --output-format stream-json "Quick Spec. $BRIEF" > $S/h1-evidence/A1.jsonl 2> $S/h1-evidence/A1.stderr < /dev/null`.
  Pass: exit 0 and the three files exist under `.kiro/specs/add-bulk-discount/`. Record whether it wrote
  `.config.kiro` and `tasks.meta.json` and which tool names the v3 engine used.
* A1b if A1 is denied `write` (C8 predicts that a non-default mode ignores a `--trust-tools` list; v3 trust is
  untested): A1 again with `--trust-all-tools` instead of `--trust-tools=read,write`, in a throwaway clone
  (`git clone $S/h1-origin.git $S/h1-author`), copying only `.kiro/specs/add-bulk-discount/` back into `$S/h1`. This is
  the headless-authoring result the task asks about; do not skip it.
* A2 fallback if A1/A1b write nothing or ask a question they cannot get answered: the same brief on the
  default v2 agent, `$K chat --no-interactive --model claude-sonnet-4.5 --trust-tools=read,write --output-format stream-json "$BRIEF"`.
* A3 last resort: the maintainer in the TUI, `kiro-cli --v3`, `/spec new add-bulk-discount`, choose Quick Spec, paste
  the brief.
* Acceptance of A (all must hold, else record the delta as a finding and re-prompt; never hand-edit silently):
  `git -C $S/h1 status --porcelain` lists only `.kiro/specs/add-bulk-discount/*`; requirements are EARS, numbered
  under `### Requirement N` / `#### Acceptance Criteria` (K11); every required leaf has a `_Requirements:_` line (K12:
  note any `**Validates: …**` form); the graph JSON parses and puts task 2's leaves in wave 0.
* Commit as the human: `git add .kiro/specs/add-bulk-discount && git commit -m "Seed add-bulk-discount (authored by kiro-cli 2.28.0, <A1|A2|A3>, claude-sonnet-4.5)"`,
  then the steering seed as its own commit, then `git push origin HEAD:main` (to the local bare origin only).
* Keep the three files as the K11 golden (`$H/tests/fixtures/…/kiro-v3-authored/` in a later harness change).

**B. L4 intake**

* B1 `$L4 doctor --repo $S/h1 --config $S/h1-cfg.yaml --unit $U` → SPEC-001 lists kiro; SPEC-002 "1 Kiro unit(s)
  validate"; SPEC-004 pass; the implementer head's probes pass (ENV-004/PRV-001 for `kiro-qwen`).
* B2 `$L4 plan --repo $S/h1 --config $S/h1-cfg.yaml --unit $U --json` → `next: implement`, task = task 2's first leaf
  (wave 0), not task 1 (document order).
* B3 implementer `[kiro-qwen]`: `$L4 run --repo $S/h1 --config $S/h1-cfg.yaml --unit $U --dry-run --probe` →
  availability `kiro-qwen ok` (fails "unrecognised answer" until K1 is in: run it once before 0a as the baseline);
  `command: kiro-cli chat --no-interactive --trust-tools=fs_read,fs_write,execute_bash [--agent l4-…] --model qwen3-coder-next --output-format stream-json --require-mcp-startup '<prompt>'`;
  the dry-run prompt names `.l4-result/result.json`.
* B4 clarifier: exercised only if the implementer raises a question in C (then `questions.md` appears under the spec
  dir and the clarifier chain answers or the unit waits, exit 11); otherwise record "not exercised".

**G. Failure paths** (run before C, on the fresh unit)

* G1 fallback: implementer `[kiro-unavail, kiro-qwen]`, `$L4 run … --dry-run --probe` → `kiro-unavail` binary
  "version 2.28.0 < min_version 99.0.0", `kiro-qwen` selected. No agent call, 0 credits.
* G2 halt and resume: implementer `[kiro-halt]`, `$L4 run --repo $S/h1 --config $S/h1-cfg.yaml --unit $U` → three
  attempts, each exit 4 before any model call (0 credits [V C5]), unit `halted`, exit 13, ledger breaker event. Then
  implementer `[kiro-qwen]` and `$L4 resume --repo $S/h1 --config $S/h1-cfg.yaml --unit $U --reason "kiro-e2e G2"` →
  ledger commit, phase leaves `halted`. (This relies on K8 being deferred, step 0c: with K8 in, exit 4 falls back
  instead of halting.)

**C. Implementation by kiro-cli only** (implementer `[kiro-qwen]`)

* `$L4 run --repo $S/h1 --config $S/h1-cfg.yaml --unit $U`, repeated while it exits 10 (continue).
* Expected: `agent.experimental{profile: kiro-qwen}` once; for each required leaf in wave order a red commit
  `test(add-bulk-discount): red for 2.x` (`L4-TDD: red`) then green `feat(add-bulk-discount): 2.x …` (`L4-TDD: green`),
  then the cart leaf; the gates (setup, baseline, lint, test) pass; every Kiro step's raw stream is kept as
  `.l4-out/agent/<run>/<task>-<red|green>-<n>.jsonl` with its `.prompt.md`; the result was written through the
  `.l4-result` symlink (record whether Kiro's `write` followed the link into the private directory [U]).
* Credits after: `/usage` again; per-step credits from `meteringUsage` sums in the raw streams.

**D. Verification**

* D1 Claude judge: verdict PASS (or a recorded non-PASS with findings); `verification.md` lists every criterion
  (`Req 1.1` …) with its tests; the independence line reads judge `claude-code` anthropic (tool) vs implementer
  `kiro-qwen` alibaba `declared (unverified)` → independent.
* D2 Kiro as judge: not supported (K13); record "not run". Optional, informational only: give the published judge
  prompt (`.prompt.md`) to `$K chat --no-interactive --trust-tools=read --model glm-5 --output-format stream-json`
  from an empty directory and compare its verdict with Claude's.

**E. Hand-off and done-gate (partial on H1)**

`make_forge` builds `LocalForge()` without a directory, so PR state does not survive between `l4` processes [V code];
the merge → sweep → archive path is H2 only. On H1:
* E1 the last `l4 run` ends `in_review`, exit 0, and pushed `l4/kiro/add-bulk-discount` to the local bare origin.
* E2 done-gate: `$L4 archive --repo $S/h1 --config $S/h1-cfg.yaml --unit $U` on the unit branch → passes with the
  optional leaf still `[ ]*`. Negative: on a throwaway copy with one required leaf reset to `[ ]`, the same command is
  refused naming that task.
* E3 human merge: `git merge --no-ff l4/kiro/add-bulk-discount` into `main` of the local clone; `pytest` and `ruff`
  green on the merge.

**F. Kiro-specific checks** (on the final unit branch; base = the steering commit)

* F1 markers byte-exact: `python3 - <<'EOF'` comparing `git show <base>:.kiro/specs/add-bulk-discount/tasks.md` with
  the head version: same length; the only differing offsets are `' '`→`'x'` of the required leaves and their parents
  (as M1.4's census: `docs/live/m14/s3-add-loyalty-points-tasks-md.txt`). No `-` or `~` is written (K9).
* F2 optional skipped: no commit, ledger event or test for the `[ ]*` leaf; it is still `[ ]*`; E2 passed anyway.
* F3 waves: the first red commit is for a task-2 leaf although task 1 comes first in the document.
* F4 traceability: each red result's `criteria` include the leaf's `_Requirements:_` criteria (ledger
  `task.red_ok.criteria`); every criterion is covered in `verification.md`.
* F5 steering (expected to differ by venue, by design L4-SEC-002 / K10): on H1 Kiro's default agent loads
  `.kiro/steering/` (no sandbox), so expect the bulk constants in `pricing.__all__` and `(Req …)` docstring endings;
  record either way. If K3 landed with `resources: []`, expect the rule **not** followed and say so.
* F6 protected: `git diff <base>..<head> -- .kiro/steering .kiro/specs/add-bulk-discount/requirements.md .kiro/specs/add-bulk-discount/design.md`
  is empty; `tasks.md` differs only by F1's bytes; ledger `guard.violation` count 0, or each one names a revert (for
  example Kiro ticking `tasks.md` itself [U]).
* F7 isolation: in every raw stream, `tool_call` events use only `read`/`write`/`shell`/`glob`/`grep`; any
  `mcpServerName` is the K3 leak; `[denied]` stderr lines are counted.

## 6. Venue H2: dummy-agentic live, CI on the shared runner

Preconditions: step 0 committed in the harness (K1 and K2 at least); `l4_idle.py` reports idle before every push and
pipeline; GitLab only through `scripts/dev/mk-gitlab-api.sh` (`rm /tmp/l4gl.env` after); SSH clone in `$S/dummy`;
identity CiprianSpot. State on 2026-10-07 [V]: 18 open MRs, all `in_review`, `awaiting_human` or `escalated`
(`!13` `l4/kiro/add-loyalty-points` `in_review`); schedule 1 `l4 sweep` `*/30 * * * *` active.

* H2-0 Optional rehearsal on the runner outside CI (as `docs/live/free/README.md` did): `forge.type: local`, a fresh
  clone of a local bare mirror, `--config` scratch, private `L4_CACHE`, run as `gitlab-runner` only when idle. This is
  the first venue with bubblewrap, so it proves K2 (Kiro logged in inside the sandbox; another adapter cannot read the
  token: `ls ~/.local/share/kiro-cli` from a codex sandbox shows an empty tmpfs) with no GitLab write.
* H2-1 One human push to `main` (pipeline allowed, not `[skip ci]`): "Upgrade the vendored L4 harness to `<sha>`
  (Kiro e2e: K1, K2, …)" (the bcca2bb procedure: `uv run --frozen --project $H l4 init --ci gitlab --vendor` in
  `$S/dummy`, keep `.l4/config.yaml`, pin `harness.commit` [I: confirm the flags against that commit]); the A-authored
  spec and the steering commit from H1 (same bytes); config: the `kiro` profile replaced by `kiro-qwen` as in H1,
  `kiro-halt` added, `roles.implementer: [kiro-halt]` (for G2), judges unchanged (`claude-code` first).
  Before pushing: `.l4/bin/l4 plan --json` in `$S/dummy` shows `kiro:add-bulk-discount` as the only actionable unit.
* H2-2 (G2) the pipeline's `l4` job: 3 × exit 4, `halted`, exit 13, MR opened as draft with `l4:halted` and the sticky
  note naming `l4:resume` [I: confirm the halt pushes the branch and opens the MR]. Then a human commit
  `roles.implementer: [kiro-qwen]` and the label as the human member:
  `scripts/dev/mk-gitlab-api.sh PUT "/projects/118/merge_requests/<iid>?add_labels=l4:resume"`; the next sweep resumes
  (ledger resume event naming the member; a label set by the bot user is refused, L4-SEC-004).
* H2-3 (C, D) the following pipelines: red/green commits by `kiro-qwen` under bwrap; Claude judge PASS; `in_review`,
  MR ready, `l4/<unit>` status success. Download the job artefacts (`.l4-out/`) for the raw Kiro streams. `/usage` as
  `gitlab-runner` before and after (a read-only `mk-ssh.sh` line, when idle); stop if more than 35 of 50 credits are
  used.
* H2-4 (E) human merge: `scripts/dev/mk-gitlab-api.sh PUT /projects/118/merge_requests/<iid>/merge`; the sweep marks
  it `merged`, deletes the WIP branch and lock ref, and opens the post-merge archive MR (L4-ARC-007, the default
  `post_merge_pr`) containing only the unit's archive change (Kiro: done-gate passed, ledger phase `archived`, no
  folder move while `kiro.archive_dir` is null); merge it as the human → `archived`.
* H2-5 (F) F1–F7 on the merged tree; F5 expected **not** followed (bwrap masks `.kiro/steering`); F7 additionally:
  no `mcpServerName` (gitlab-runner has no `mcp.json` [V]).
* H2-6 (G1) `roles.implementer: [kiro-unavail, kiro-qwen]` is shown with `l4 plan --probe` in a local clone (no push).
* H2-7 Restore: a human commit putting back the dummy's free-first `roles.implementer` chain with `kiro-qwen` appended
  after the free OpenCode models (free-resources: Kiro is an implementer fallback), and the `kiro` profile entry
  replaced, not left as `vendor: amazon`.

## 7. Budget, stop rules, evidence

* Credits [I, from C11]: one red or green step of ~20–40 turns ≈ 0.2–1.2 credits on `qwen3-coder-next`, ×5 on
  `deepseek-3.2`, ×10 on `glm-5`, ×26 on `claude-sonnet-4.5`. A 2-leaf unit with retries is 4–8 steps: qwen fits the
  FREE 50 easily, deepseek fits one unit, Sonnet does not. H1 runs on the Mac's PRO 1000.
* Stop when: a Kiro run touches a path outside the worktree or the step's private directory; any `guard.violation` on
  a path other than `tasks.md`; an MCP tool appears on H2; credits on `gitlab-runner` pass 35; the runner is busy
  (wait, do not queue behind other workflows). Never copy, move or print a Kiro, Claude or Codex credential; never put
  an e-mail in evidence.
* Evidence goes to `docs/live/kiro-e2e/` in the harness (job logs, ledgers, raw Kiro streams, the F1 byte report,
  `/usage` before/after), indexed in `docs/live/README.md`, with this plan's step ids.

## 8. Open items

* **kiro-cli 3.0** (end of October 2026) makes the V3 agent engine the default and adds model fallback notices. The Kiro
  judge pins `--v2` and `chat.agentEngine: "v2"`, and a judge run that reports another engine is an error (L4-KJD-003).
  Before the recorded version or a profile's `min_version` moves to 3.x: re-record the 2.32.0 shapes under
  `tests/fixtures/recorded/kiro-cli/2.32.0/` against 3.0 (the stream, the session file, `--list-models`, whether `--v2`
  is still accepted), and decide whether V3's fallback notices become a served-model source (L4-KJD-015).
