## Why

OpenCode 2 (`@opencode/cli`, 2.0.32) is where OpenCode development now happens. v1 is still maintained (1.19.3 on
2026-10-16, 1.19.4 on 2026-10-22; v2 is at 2.1.4 on 2026-10-24, with the same CLI surface as 2.0.32), but v2 changes the four things the `opencode` adapter's outcome rests on (`docs/plan/opencode-v2.md`,
recorded in an isolated HOME):

1. **Success detection.** The final `step_finish` is missing in 13 of 16 successful runs (row 14). Today's rule (last
   reason `stop`) would turn most v2 successes into `error` and lose usage, cost and the context peak.
2. **`ask`.** A rejected `ask` no longer ends the run: v2 continues, and a free judge (`refuse="ask"` for `opencode/`
   models) made 30 rejected tool calls in 151 s until its timeout (row 10). The free judge and the free implementer
   fallbacks rely on that rule.
3. **Errors.** The `error` event has a new schema (`type`, `message`, `status`, `response.body`), so auth and
   limit classification silently stop (row 13), and the denial texts changed (row 11).
4. **The shared daemon.** Without `--standalone`, v2 runs every client through one per-user daemon that keeps the
   first client's environment: one job is served another job's permission rules, and its own key is invisible
   (row 8).

The major gate (`opencode-major-gate`, row 51) makes the harness refuse v2 where it expects v1. This change lets a
profile opt in to v2, and handles each of the four points.

## What Changes

- **Opt-in selection** (L4-OCV-001): `options.cli_major: 1 | 2` on an `opencode` profile, default 1, with no automatic
  switching. A v2 profile runs `opencode2` and requires major 2. A v2 profile is refused at load when it sets
  `options.provider` (the custom-provider key form is unverified on v2), names a renamed provider, or lists the
  `list` tool. `options.steps` on a v1 profile is refused. The v2 adapter is `experimental` until the live
  validation.
- **Its own install** (L4-OCV-002): `@opencode/cli@2.0.32` (`OPENCODE2_VERSION`) in `$L4_HOME/npm-opencode2`, linked
  only as `~/.local/bin/opencode2`, part of `catalog_hash`, PRQ-20 in `prereqs.sh` behind `--with-opencode2`.
- **`--standalone` on every v2 call** (L4-OCV-003), with a private `XDG_STATE_HOME` per call. The harness never
  starts a v2 subcommand that lacks the flag, such as `debug config`.
- **argv and environment** (L4-OCV-004): `opencode2 run --standalone --format json -m <m> --title <t>`, the cwd as
  today, the prompt on stdin. No `--pure` and no `--dir`. The four `OPENCODE_DISABLE_*` switches plus
  `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`.
- **Native v2 configuration** (L4-OCV-005): an ordered `permissions` array with the same effective rules as today,
  `snapshots`, `update: "disable"`, and no `list` or `doom_loop`. New `skill` and `subagent` rules are refused like
  `bash` is today.
- **Per-role step bounds** (L4-OCV-006): `agents.build.steps` 3 for judge-mode calls (judges, clarifier, verifier
  calls, readiness, hello) and 200 for the implementer, configurable per profile with `options.steps`. A
  bounded run is never `ok`.
- **Status and usage from the session export** (L4-OCV-007, -008): `ok` needs exit 0, no `error` event, the step
  bound not reached, and `opencode2 session export <id> --standalone` saying `outcome: "succeeded"`. Usage, cost and
  the context peak come from the export.
- **v2 errors, limits and denials** (L4-OCV-009), **auth from `auth list --standalone --format json`**
  (L4-OCV-010), and a v2 reply's leaked leading `…</think>` is stripped (L4-OCV-011).
- **Probe, doctor and recorded versions per major** (L4-OCV-012): ENV-004 and LIVE-005 check the profile's own
  binary; LIVE-005 compares recorded versions of the same major. Fixtures go under
  `tests/fixtures/recorded/opencode/2.0.32/`.
- **No v2 delegate yet** (L4-OCV-014): a `cli_major: 2` profile in `roles.delegate` is refused at load, because the
  delegate's read-only mode is not recorded on v2.
- **0.4.28 amendment** (design E1 to E7): resumed on the 0.4.27 tree; the shared major gate gains an `opencode2` key,
  `pin-clis` applies to `opencode2` (`ci.cli_versions`, exact pin, ENV-015), PRQ-20 keeps its reserved number, and
  the live validation runs only on an ephemeral runner.
- **Every [U] fact on a named fallback** (L4-OCV-013). Each has a test that pins the fallback, the SPEC's [U]
  marker, and an orchestrator task that records it in CI on the owner's dummy repository with a real
  `OPENCODE_API_KEY`. No parser for a [U] shape is written before its fixture exists.

## Impact

- Capability `opencode-v2-adapter`. Code:
  - new `src/l4/agents/opencode_v2.py`
  - `src/l4/agents/opencode.py` (shared helpers stay; v1 behaviour unchanged)
  - `src/l4/agents/factory.py`
  - `src/l4/config/schema.py` (`OpencodeOptions`)
  - `src/l4/availability/limits.py`
  - `src/l4/provision/{catalog,runner,install}.py`
  - `src/l4/doctor/{checks_env,checks_agents}.py`
  - `src/l4/recordedversions.py`
  - `scripts/runner/prereqs.sh`
- **v1 is unchanged.** A profile without `options.cli_major` gets byte-identical argv and `OPENCODE_CONFIG_CONTENT`,
  and no step bound.
- **Every consumer's agent-CLI cache is rebuilt once on upgrade.** `catalog_pins` gains `agent:opencode2` and
  `npm:opencode2`, which changes `catalog_hash` (L4-ACT-002) whether or not a v2 profile exists.
- **The harness path never resolves v2 as `opencode`.** The v2 curl installer's directory (`~/.opencode/bin`) is on
  `harness_path`. The v1 link in `~/.local/bin` comes first, and the major gate (row 51) refuses a v2 found as
  `opencode`. On the runner's login shell PATH (`prereqs.sh`), a v2 may still come first, and PRQ-11 then reports it
  FAILED with the path.
- Depends on `opencode-major-gate`, `pin-clis`, `kiro-judge` and `delegate-answers`, all shipped by 0.4.27.
- No new runtime dependency.
