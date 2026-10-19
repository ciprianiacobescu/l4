## Why

OpenCode 2 is released as a separate npm package (`@opencode/cli`, 2.0.32 on 2026-10-16) whose binary is also
called `opencode`. It rejects `--pure` and `--dir` with `Unrecognized flag`, exit 1, so every run and hello of the
`opencode` adapter fails on it. The harness does not notice, as recorded in an isolated HOME and read in the code
(`docs/plan/opencode-v2.md`, rows 3–5):

1. `scripts/runner/prereqs.sh` PRQ-11 compares `opencode v2.0.32` with `1.18.34` through `sort -V`, which puts the
   digit first, so the check passes.
2. The probe `binary` step and doctor ENV-004 compare versions only when the profile sets `min_version`, and
   `2.0.32 >= 1.18.34` passes when it does.
3. `l4 doctor --fix` leaves a present tool alone when it meets its floor, so a v2 `opencode` already on a runner is
   accepted.
4. Doctor LIVE-005 only warns ("unrecorded version").
5. The hello fails with exit 1 and no event, which `_hello` classes `transient`. The profile looks unavailable, the
   unit parks in `waiting_capacity`, and nothing names the cause.

## What Changes

- **The major is read from every `opencode --version`** (L4-OCG-001): one shared function accepts `1.18.34` and
  `opencode v2.0.32`. The supported major of the `opencode` adapter is the major of the pinned `OPENCODE_VERSION` (1).
  The probe, ENV-004, LIVE-005, `doctor --fix` and PRQ-11 compare it whether or not the profile sets `min_version`.
- **A wrong major fails closed with a named reason** (L4-OCG-002): the probe `binary` step fails with "opencode 2.0.32
  is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 (`l4 doctor --fix` installs it
  user-locally) or set options.cli_major: 2 when supported". ENV-004 lists the profile as failing. LIVE-005 fails
  with severity `error`, never a warning. `l4 doctor --live` reports the same reason.
- **A rejected flag is `unsupported_version`** (L4-OCG-003): a hello or a run whose stderr says `Unrecognized flag:
  --pure` or `--dir` gets the new failure class `unsupported_version` (hello) or the detail prefix
  `unsupported_version:` (run). It is never `transient` and never cached, so a fix takes effect at the next probe.
- **Provisioning installs the pinned v1 instead** (L4-OCG-004): `doctor --fix` treats a wrong major as not satisfied
  and installs `opencode-ai@1.18.34` into the harness's own npm prefix, linked as `~/.local/bin/opencode`. It never
  replaces a regular file there, and it verifies the major of the binary the harness path resolves after the
  install. PRQ-11 passes only a v1 at least the pin, and fails naming the path when a v2 still comes first on the
  runner's login PATH. PRQ-15 runs `opencode models` only when PRQ-11 passes, because v2's `models` starts the shared
  daemon.
- Docs: SPEC L4-FAC-007 (what an unsupported major does), the change table (row 51), §8.3's opencode row (the
  gate), Part II scenarios, a runbook troubleshooting entry under 7.4, and CHANGELOG `## 0.4.18 (unreleased)`.

## Impact

- Capability `agent-cli-major`. Code: `src/l4/versions.py`, `src/l4/provision/catalog.py` (the supported-major
  table), `src/l4/availability/probes.py` (`_binary`), `src/l4/agents/base.py` (`FailureClass`),
  `src/l4/agents/opencode.py` (`_hello`, `run`, `parse`), `src/l4/availability/fallback.py` (`_remember` comment and
  rule), `src/l4/doctor/checks_env.py` (ENV-004), `src/l4/doctor/checks_agents.py` (LIVE-005),
  `src/l4/provision/runner.py` (`is_satisfied`), `src/l4/provision/install.py` (`_link`, `_verified`),
  `scripts/runner/prereqs.sh` (PRQ-11, PRQ-15).
- Fixtures under `tests/fixtures/cli_major/opencode/`, outside `tests/fixtures/recorded/`, so `recorded_versions.json`
  does not change: no v2 version counts as "recorded" for the v1 adapter.
- No new config key and no new runtime dependency. Only the `opencode` adapter is gated. Claude Code updates itself
  and Codex is 0.x, so gating them is a separate decision.
- The link guard is scoped to the gated agent link (`opencode`). The Node links, `laya-serve` and the codex link
  still replace whatever is at their path, as before.
- Behaviour change: a runner whose `opencode` is v2 now fails the opencode profiles at the `binary` step with a named
  reason, where it used to fail at the hello as `transient`. `doctor --fix` now installs v1 there.
- Independent of `opencode-v2` (change table row 52), which builds on it.
