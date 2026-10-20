# kiro-cli judge live in CI (kiro-judge task 11.1, 2026-10-20)

**Verdict: both legs reached a verdict from a kiro-cli judge, and the negative leg made no judge call. No STOP condition
of task 11.1 occurred.** Three findings need a decision before release (below): the Kiro `quota` step needs more than
the default 20 s probe step timeout on a GitHub-hosted runner; a pinned model id the account does not have fails the
prompt (a `runError`) instead of the stderr warning of R20; and the listing's JSON has a top-level `default_model`.

Venue: the owner's dummy repository (public, throwaway), GitHub-hosted `ubuntu-24.04`, action delivery. The setup
action was pinned to the snapshot branch `live/kiro-judge` (`26332393`: the tree of the kiro-judge branch at `0a04fef4`
on 0.4.18; `run.started.harness_version` 0.4.18). Self-provisioning installed kiro-cli from its installer, which takes no
version and served **2.32.0** (within 2.32.0 to below 3.0, design §7). `KIRO_API_KEY`, `OPENCODE_API_KEY` and
`CLAUDE_CODE_OAUTH_TOKEN` came from the repository's `l4` environment. No job ran `kiro-cli whoami` or printed account
data. Labels: [V] observed in these runs, [I] inferred from them, [U] not checked.

## Configuration

```yaml
profiles:
  deepseek:    {adapter: opencode, model: opencode-go/deepseek-v4.1-flash, auth: api_key, vendor: deepseek}
  kiro-auto:   {adapter: kiro-cli, auth: api_key, min_version: "2.32.0"}                      # no model: auto
  kiro-sonnet: {adapter: kiro-cli, model: claude-sonnet-5.5, auth: api_key, vendor: anthropic, min_version: "2.32.0"}
  kiro-bogus:  {adapter: kiro-cli, model: claude-sonnet-9.9, auth: api_key, vendor: anthropic, min_version: "2.32.0"}
  claude-impl: {adapter: claude-code, model: claude-sonnet-5-5, auth: subscription, vendor: anthropic}
availability:
  probe_step_timeout: 120s   # from run 2 on: the quota step did not answer within the default 20 s (finding 1)
```

| Leg | `roles.implementer` | `roles.judges` | Unit (one new OpenSpec change each) |
|---|---|---|---|
| auto | `[deepseek]` | `[kiro-auto]` | `add-days-of-stock` (3 criteria) |
| pinned | `[deepseek]` | `[kiro-bogus, kiro-sonnet]` (kiro-bogus is the R20 probe) | `add-spare-items` (3 criteria) |
| negative, in turn | `[claude-impl]` | `[kiro-auto]`, then `[kiro-sonnet]` | `add-shelf-gap`, implemented once, verified twice |

Deviations from design D11, all on the dummy repository only: the workflow's doctor step was edited by hand to `l4
doctor --ci --live --fix` (the generated step runs `--ci` only, and LIVE-001 has scope `live`); `ci.upload_artifacts`
was on for the two verdict legs, to get the harness's published judge streams, and off for the negative leg; a
listing-only workflow (`kiro-models.yml`: `kiro-cli --version`, `chat --list-models --format json` and `settings list`
under a private `KIRO_HOME`; no `whoami`, no `/usage`) recorded the raw listing, which the harness never logs (it keeps
derived data only, D14).

## Runs

| # | Run / job | What | Result | Evidence |
|---|---|---|---|---|
| 1 | 39367262021 / 118446825773 | listing-only workflow | success: kiro-cli 2.32.0; listing exit 0 from a private `KIRO_HOME`; `settings list` shows the 4 judge settings as `(global)` | [job-118446825773-list-models.txt](job-118446825773-list-models.txt), [../../../tests/fixtures/recorded/kiro-cli/2.32.0/list-models.json](../../../tests/fixtures/recorded/kiro-cli/2.32.0/list-models.json) |
| 2 | 39367383388 / 118447200897 | auto, attempt 1 | **failure at doctor**: LIVE-001 `profile kiro-auto failed the quota probe: kiro-cli did not answer within 20 s (quota step)`, exit 3 | [job-118447200897-auto-quota-timeout.txt](job-118447200897-auto-quota-timeout.txt) |
| 3 | 39367684984 / 118448154776 | auto, `probe_step_timeout: 120s` | **success**: doctor CFG-011 and LIVE-001 pass; `add-days-of-stock` red, green, **PASS** (3/3) by kiro-auto, PR #8 `l4:in_review`, exit 0 in 192 s | [job-118448154776-auto.txt](job-118448154776-auto.txt), [auto-ledger.jsonl](auto-ledger.jsonl), [auto-judge.stream.jsonl](auto-judge.stream.jsonl) |
| 4 | 39368557956 / 118450908856 | pinned, attempt 1 | doctor pass (kiro-bogus skipped, kiro-sonnet selected); the unit was rejected before any agent: its new capability's `## Purpose` had 46 characters, the harness needs 50 (exit 14; the change was fixed) | [job-118450908856-pinned-rejected-spec.txt](job-118450908856-pinned-rejected-spec.txt) |
| 5 | 39368942857 / 118452164860 | pinned | **success**: kiro-bogus skipped, kiro-sonnet `fallback #1`; `add-spare-items` **PASS** (3/3) by kiro-sonnet, PR #9 `l4:in_review`, exit 0 in 215 s | [job-118452164860-pinned.txt](job-118452164860-pinned.txt), [pinned-ledger.jsonl](pinned-ledger.jsonl), [pinned-judge.stream.jsonl](pinned-judge.stream.jsonl) |
| 6 | 39369682649 / 118454505419 | negative, kiro-auto | claude-impl implemented `add-shelf-gap` (red, green); verification: `kiro-auto skipped — judge profile kiro-auto and implementer profile claude-impl share the vendor` → `waiting_capacity` (`no independent verifier`), exit 12, **no judge call** | [job-118454505419-negative-auto.txt](job-118454505419-negative-auto.txt), [negative-ledger.jsonl](negative-ledger.jsonl) |
| 7 | 39370048286 / 118455637542 | negative, kiro-sonnet | the same unit, `waiting_capacity → verifying (capacity_restored)`: `kiro-sonnet skipped — … share the vendor` → `waiting_capacity`, exit 12, **no judge call** | [job-118455637542-negative-sonnet.txt](job-118455637542-negative-sonnet.txt), [negative-ledger.jsonl](negative-ledger.jsonl) |

## The auto leg (run 3)

- Doctor: `CFG-011 pass  kiro-auto: tool-less harness agent, prompt on stdin, no trust flag, model auto, routed to
  anthropic, minimax, zhipu (built-in); …` (`built-in` on a fresh runner, finding 4), `LIVE-001 pass  implementer: deepseek ok (hello 3898 ms); judges: kiro-auto ok (hello 25390 ms)`. [V]
- Probe: `kiro-auto ok (binary 2.32.0 · auth api_key · auto: anthropic, minimax, zhipu (listed) · quota 44.3% used
  (credits) · hello 25.4s)`. `auth api_key` is the credential variable (`credential_auth`), so `whoami` never ran;
  `(listed)` is the harness's own listing from a private `KIRO_HOME`. [V]
- `verify.judge {round 1, profile kiro-auto, status ok, calls 1, model null, template judge@11, credits 0.206702}`,
  `budget.cost {credits 0.206702, credits_source kiro.stream, profile kiro-auto, role judge}`,
  `verify.verdict PASS 3/3`. [V]
- Independence line (`verification.md` on the unit branch): `independence: routed (unverified): kiro-auto routed:
  anthropic, minimax, zhipu (auto), deepseek deepseek (declared)`, as SCN-KJD-28 asks. [V]
- Stream ([auto-judge.stream.jsonl](auto-judge.stream.jsonl), also the fixture `judge-pass.stream.jsonl`): the D3 shape
  exactly. `runStarted {payloadSchema acp, acpProtocolVersion 1, engine v2}`, 3 `metadata` (`contextUsagePercentage`,
  `reasoning: {support: "unavailable"}`; the last with `meteringUsage` 0.20670165854063016 credits and
  `turnDurationMs` 15727), 245 `agent_message_chunk` events whose texts join to `finalText`, `runFinished {status
  success, stopReason end_turn, finalTextTruncated false}`. The reply is the bare verdict object (no sentence before it).
  No `tool_call`, no `runError`, and no event names a model. [V]
- Standard error of the judge call: empty (the published `.stderr` had 0 bytes). [V]
- Session file `model_id`: the harness reported no served model (`verify.judge.model` null, line `routed`, not
  `served`), so the file named no concrete model: it said `auto`, or it was missing or unreadable (D15 reads it
  fail-open). Which of these it was cannot be seen from the log, the ledger or the artifacts; the file sits in the
  step's private `KIRO_HOME` and is not published. `auto` is the likely value, since R11 records the CLI's own
  selection. [V] for "no concrete id", [I] for `auto`.
- Fallback notice: none (no event outside the four types above; empty stderr). [V]
- An agent file with `"model": "auto"`: accepted. Every kiro-auto hello and the judge call ran with it and `--model
  auto`, exit 0, with no `runError` at stage `init`. [V]

## The pinned leg (run 5)

- Doctor: `CFG-011 pass  kiro-bogus: … model claude-sonnet-9.9 (anthropic); kiro-sonnet: … model claude-sonnet-5.5
  (anthropic)`; `LIVE-001 pass  implementer: deepseek ok (hello 4135 ms); judges: kiro-sonnet ok (hello 26478 ms)`. [V]
- R20 probe: `judges: kiro-bogus skipped — hello: kiro-cli reported runError (prompt)`, then `kiro-sonnet ok (binary
  2.32.0 · auth api_key · quota 44.3% used (credits) · hello 26.5s) → selected, fallback #1`. The ledger has the skip
  as `{"profile": "kiro-bogus", "step": "hello", "reason": "kiro-cli reported runError (prompt)"}`. A pinned profile is
  never listed (no `auto:` part in the probe text). [V]
- `verify.judge {profile kiro-sonnet, status ok, calls 1, model null, credits 0.390773}`, `budget.cost {credits
  0.390773, role judge}`, `verify.verdict PASS 3/3`. [V]
- Independence line: `independence: declared (unverified): kiro-sonnet anthropic (declared), deepseek deepseek
  (declared)`, which names `kiro-sonnet anthropic` as SCN-KJD-28 asks. [V]
- Stream ([pinned-judge.stream.jsonl](pinned-judge.stream.jsonl)): the same D3 shape. 339 `agent_message_chunk`
  events, `meteringUsage` 0.39077286940298506, `turnDurationMs` 12169, `runFinished {success, end_turn,
  finalTextTruncated false}`, the bare object, no `tool_call`, no model named. One difference from auto: `metadata.reasoning`
  is `{support: "alwaysOn", effortLevels: [low, medium, high, xhigh, max]}` from the second event on, where the auto
  run said `unavailable` throughout. [V] The CLI thus knew the reasoning support of the pinned model but not of `auto`'s
  pick. [I]
- Stderr of the judge call: empty. Session file: no mismatch was reported, so it named `claude-sonnet-5.5` (normalised),
  `auto` or nothing. D15 reports nothing for a match by design, so the exact value is not observable. [V] / [I]
- Fallback notice: none. [V]

## The negative leg (runs 6 and 7)

- Run 6: `availability.unavailable {role judges, skipped: [{profile kiro-auto, step constraint, reason "judge profile
  kiro-auto and implementer profile claude-impl share the vendor"}]}` and `phase.changed verifying → waiting_capacity
  (required_role_unavailable)` with the reason `role judges is unavailable: no independent verifier (profile kiro-auto:
  …)`. `anthropic` is among auto's possible vendors. [V]
- Run 7: the same unit, after `waiting_capacity → verifying (capacity_restored)` and a base merge: the same events for
  `kiro-sonnet`. [V]
- The unit's ledger has **0** `verify.judge` events and **0** `budget.cost` events with `role: judge`. The veto is at
  `step: constraint`, before any judge probe of the verification. The doctor's LIVE-001 still probed the judge, since it
  checks no independence. [V]

## Design §2.3 answered

| Question | Answer | Label | Where |
|---|---|---|---|
| A successful judge reply on 2.32.0 | `runFinished {status: "success", stopReason: "end_turn", finalText, finalTextTruncated: false}`; the reply text is in `finalText` and in the chunks | [V] | runs 3, 5 |
| Does any event name the model that served it? | No. No event of either stream has a model field. Under auto the harness got no concrete id from the session file either; under the pin it reports nothing for a match | [V] | streams, `verify.judge.model` null |
| A 150 kB judge prompt end to end | Not exercised: both prompts were about 12 kB (published prompt documents 12,218 and 12,364 bytes). Stdin itself carried them on the runner's 2.32.0 (D2) | [U] / [V] | runs 3, 5 |
| `"tools": []` gives no `tool_call` | None in either stream | [V] | streams |
| Credits per judge call | auto: 0.20670165854063016; `claude-sonnet-5.5`: 0.39077286940298506 (1.89 times as much, for a reply 1.37 times as long). `verify.judge.credits` and `budget.cost{credits, role: judge}` carry them rounded to 6 places | [V] | ledgers |
| Out-of-credits wording | Not seen (the plan stood at 44.3 % used) | [U] | - |
| Throttling on 2.32.0 | Not seen | [U] | - |
| Is `settings/cli.json` under `KIRO_HOME` read? | Yes, by the CLI's settings layer: with `KIRO_HOME` set to a directory that held only that file, `kiro-cli settings list` printed its 4 keys with their values as `(global)`. Whether `chat` acts on each key is not separately visible (the engine is also pinned by `--v2`, and the cwd is empty anyway) | [V] / [I] | run 1 |
| Stdin on the runner's installed version | 2.32.0 took the judge prompt on stdin and answered it | [V] | runs 3, 5 |
| auto: the session file's `model_info.model_id` | Not a concrete model (none reported); `auto` is likely; not observable without publishing the CLI's internal file | [V] / [I] | run 3 |
| A pinned run's session file | No mismatch; exact value not reported by design (D15) | [V] / [I] | run 5 |
| Any fallback notice | None, in either leg (v2 is pinned) | [V] | runs 3, 5 |
| The stderr warning when a pinned model cannot be set (R20) | Not produced. `claude-sonnet-9.9` failed the hello (the judge invocation with the prompt as argument) with a `runError` at stage `prompt`, which is R16's "the first prompt can fail" and not R20's "warns and continues". The message's wording is not observable: the hello records the stage only | [V] / [U] | runs 4, 5 |
| Is an agent file with `"model": "auto"` accepted? | Yes | [V] | run 3 |
| Does `--list-models --format json` carry a status field? | No. Each entry has exactly `model_name`, `description`, `model_id`, `context_window_tokens`, `rate_multiplier`, `rate_unit`; Experimental is only in the description. New against R18: a top-level `"default_model": "auto"` | [V] | run 1 |
| Does the listing cost credits? | Not measured: `/usage` reports a rounded percentage, read after the listing within the same ladder | [U] | - |
| Does the listing work from a private `KIRO_HOME`? (inferred, not run, when the review fix `0a04fef4` moved it there) | Yes. Exit 0 in the listing workflow with `KIRO_HOME` holding only the judge's settings, and `(listed)` in the harness's own `auth` step in runs 3 and 6 | [V] | runs 1, 3, 6 |
| The listing's Active set against the built-in one | Equal: the 12 ids of R18 (`claude-sonnet-5.5`, `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4.8`, `claude-opus-4.7`, `claude-opus-4.6`, `claude-sonnet-4.6`, `claude-opus-4.5`, `claude-sonnet-4.5`, `claude-haiku-4.5`, `minimax-m2.5`, `glm-5`), vendors anthropic, minimax, zhipu; the 8 Experimental ones by description, as R18. `test_vendor_kiro.py` passes on the recorded file | [V] | run 1 |

## Findings

1. **The Kiro `quota` step needs more than 20 s here.** `kiro-cli chat --no-interactive /usage` with an API key did not
   answer within the default `availability.probe_step_timeout` (20 s) in run 2, so LIVE-001 failed and so would every
   judge selection. With 120 s it answered (`quota 44.3% used (credits)`). The step's duration is not logged. From the
   log timestamps (ladder time minus the hello minus binary and auth) it took about 23 to 30 s in runs 3, 5 and 6. [V]
   for the timeout, [I] for the duration. As shipped, a kiro-cli profile on a GitHub-hosted runner does not pass its
   probe without a config change. That is a harness fix decision (a longer default for this step, or a per-adapter step
   timeout), not part of this task.
   **Resolved after this run:** the adapter declares a floor of 90 s for the `/usage` call and the `auth` step's model
   listing, used as the longer of `probe_step_timeout` and the floor and still capped by `probe_timeout` (default 60 s,
   so 60 s unless it is raised; 23 to 30 s fits twice over). Every probe step now records `step_ms`, and a step of a
   second or more shows its time in the `l4 probe` line, in `availability.selected` and in the doctor LIVE-001 line
   (L4-AVL-012). The 120 s override in the configuration above is no longer needed.
2. **An unknown pinned model fails the prompt.** On 2.32.0 (engine v2) an id the account does not have gives a
   `runError` at stage `prompt` in the hello, so the profile is skipped and the next judge is selected. R20's documented
   stderr warning did not appear. D15's stderr-warning check (and its provisional pattern) stays unexercised, and the
   `runError` path is the one that protects the verdict. [V]
   **Resolved after this run:** the hello's reason now ends with the `runError` message, redacted (no e-mail, ARN,
   account, profile or request id, no path) and cut to 200 characters, so the next live run records the wording
   (L4-KJD-007). Design R20 and D15 and L4-KJD-015 say what was observed, and keep the stderr check as a second guard.
3. **The listing has `default_model`.** `{"default_model": "auto", "models": [...]}`; `routed_from_listing` reads
   `models` only and is unaffected (harmless; a test pins that a listing with the key parses the same as one without
   it, L4-KJD-013). [V]
4. On a fresh runner the doctor's CFG-011 line says `built-in` while the probe printed in the same job says `listed`
   (cosmetic) [V]. The cause is probably that CFG-011 reads the availability cache before LIVE-001 has probed [I].
   **Resolved after this run:** with no probe of the profile recorded, CFG-011 says `built-in (no listing recorded
   yet)`; a recorded failed listing still says `built-in` (L4-KJD-009).
5. A kiro-cli hello takes 25 to 28 s (auto and pinned), and a judge turn took 12 to 16 s on prompts of about 12 kB. [V]

## Account data and redaction

- Every job log of runs 1 to 7 was downloaded and scanned right after its run for an e-mail shape, `arn:aws`,
  `profile_arn` and `accountId`: no hit. No run's logs were deleted.
- The `l4-out` artifacts of runs 3, 4 and 5 (public while they exist) were downloaded, scanned and deleted on GitHub
  within minutes of the run. Run 2 uploaded none. The only pattern hits were `@pytest.mark` decorators in test code,
  which the e-mail pattern matches: 20 in run 3, 36 in run 5, none account data. Runs 6 and 7 uploaded nothing.
- The two judge streams are the harness's published copies (secrets masked; no `[REDACTED` marker was needed), with
  only the `sessionId` replaced by `00000000-0000-4000-8000-000000000000`. They contain no e-mail, no account or
  session id and no filesystem path.
- The job log extracts keep the harness steps only. Timestamps, ANSI codes and the steps' `env:` dumps are removed, and
  the runner's paths read `<runner>` and `<checkout>`. The ledger extracts leave out the plan's absolute credit counts
  (`credits_used`, `credits_included`); the percentage stays.
