## Why

The owner asked whether kiro-cli has breaking changes, then decided: "Let's pin the versions in L4". Today three of the
four agent CLIs that L4 installs have a pin, and the fourth does not:

1. **Kiro is installed as released.** `INSTALLER_URLS["kiro-cli"] = "https://cli.kiro.dev/install"`, and the catalog
   says "Kiro's installer takes no version argument and ships no changelog we can pin to [U]: it is installed as
   released"; `catalog_pins()` lists no Kiro entry, so the agent-CLI cache key does not move when Kiro does [V code].
   The installer downloads `https://prod.download.cli.kiro.dev/<channel>/latest/<file>` and checks it against
   `<channel>/latest/manifest.json`, a file fetched in the same run [V: the installer script]. The stable channel serves
   2.32.0 since 2026-10-16, which has no public release notes (the changelog ends at 2.31.1). Kiro's blog
   (2026-10-09) says V3 "becomes the default with the CLI 3.0 rollout" by the end of October 2026; `--v2` is documented
   only as "applies to that launch only" [D]. L4's kiro-cli adapter always passes `--v2` and refuses a judge stream on
   any engine but v2 [V code]. The next fresh install may therefore be a 3.x that L4 never recorded.
2. **The self-hosted script updates Kiro instead of pinning it.** `scripts/runner/prereqs.sh` PRQ-12 runs `kiro-cli
   update --non-interactive` over an existing install and treats `KIRO_VERSION` as a floor [V code].
3. **A pinned CLI can still drift.** `l4 doctor --fix` leaves a present tool alone when it is at least the profile's
   floor (`ToolSpec.min_version`: "a present tool at least this new is left alone") [V code], and only OpenCode is
   started with its self-update off (`OPENCODE_DISABLE_AUTOUPDATE=1`, `autoupdate: false`) [V code]. Claude Code's
   native install "automatically update[s] in the background" [D]. A probe runs `claude` with the real `HOME`, so on a
   persistent runner the harness's own probe can move the version it then runs [I].

## What Changes

- **Kiro gets a pin** (L4-PRV-042): `KIRO_VERSION = "2.32.0"`. It is installed from the versioned archive
  `https://prod.download.cli.kiro.dev/stable/2.32.0/kirocli-<arch>-linux[-musl].zip`, never from `latest`. Its sha256
  is checked against a table in the harness (per architecture and libc), never against a file fetched at install
  time. The harness extracts exactly `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` into `~/.local/bin` (the vendor's
  layout) and runs no script from the archive. musl is chosen as the vendor's installer chooses it. On macOS nothing
  is installed: doctor names the pinned disk image and its sha256. `catalog_pins()` gains `agent:kiro-cli`, so the
  agent-CLI cache key moves with the pin.
- **The pin is exact where L4 installs, in CI** (L4-PRV-043): `l4 doctor --ci --fix` replaces a present agent CLI of
  another version with the pin. A person's `l4 doctor --fix` never replaces a present CLI: doctor warns with the
  installed and pinned versions and the command. `prereqs.sh` PRQ-12 installs the pinned archive with the same digest
  check, compares exactly, and no longer runs `kiro-cli update`.
- **Self-update off** (L4-PRV-044): every Claude Code process the harness starts gets `DISABLE_AUTOUPDATER=1` and
  `DISABLE_UPDATES=1`; every `codex exec` gets `-c check_for_update_on_startup=false`; every private `KIRO_HOME` the
  harness writes, the implementer's included, holds `app.disableAutoupdates: true`; OpenCode keeps its switches.
  `prereqs.sh` PRQ-21 turns the background update off for the runner user's Claude Code and Kiro.
- **A major gate for kiro-cli** (L4-OCG-005): `SUPPORTED_MAJORS["kiro-cli"] = 2`. The probe, doctor ENV-004 and
  LIVE-005, `doctor --fix` and PRQ-12 refuse a kiro-cli 3.x with one sentence that names the cause and `install
  kiro-cli 2.32.0`.
- **A consumer override** (L4-PRV-045): `ci.cli_versions: {<adapter>: "N.N.N"}` holds a CLI at another version of
  the same major without editing the harness. It is validated at load, shown by doctor, used by provisioning and the
  probe, and part of the agent-CLI cache key. A Kiro override must be a version whose digests the harness holds.
- **Installed versus pinned is reported** (L4-PRV-046): doctor `ENV-015` (warn), the probe's `binary` step (`pin`,
  `pin_source`), the probe line on a drift, `l4 probe --json`, and `availability.selected` on a drift.
- **Docs**: SPEC (the requirements and scenarios, §3.2, the doctor table, §8.3's kiro row, L4-DOC-002, row 57),
  runbook 7.4 and a new 10.7, `docs/runner/README.md`, the skill's `adopt.md` and its error table, CHANGELOG
  `## 0.4.20 (unreleased)`.

## Impact

- Code: `src/l4/provision/catalog.py` (Kiro pin, URL, digest table, `kiro_platform`, `SUPPORTED_MAJORS`,
  `major_problem` wording per adapter, `catalog_pins`, `catalog_hash`, `effective_pins`, `manual_command`),
  `src/l4/provision/runner.py` (`is_satisfied`, `plan_fixes(replace_present=…)`), `src/l4/provision/install.py`
  (`_install_kiro`, `_verified` wording), `src/l4/config/schema.py` (`CiCfg.cli_versions`), `src/l4/doctor/context.py`
  (`ci`), `src/l4/doctor/run.py`, `src/l4/doctor/checks_provision.py`, `src/l4/doctor/checks_env.py` (ENV-004 wording,
  new ENV-015), `src/l4/doctor/checks_agents.py` (LIVE-005), `src/l4/agents/base.py` (`ProbeCtx.pins`),
  `src/l4/agents/factory.py`, `src/l4/availability/probes.py` (`_binary`, `probe_claude` env),
  `src/l4/availability/fallback.py` (`probe_identity`, `_step_text`, `to_event`), `src/l4/agents/claude_code.py`
  (`extra_env`), `src/l4/agents/codex.py` (`build_command`, the probe argv), `src/l4/agents/kiro_cli.py`
  (`write_harness_agent`), `scripts/runner/prereqs.sh` (top block, PRQ-12, new PRQ-21), `scripts/kiro_pin.py` (new,
  maintenance only).
- Config: one new key, `ci.cli_versions` (default `{}`). The schema is strict, so a consumer moves its harness pin to
  0.4.20 before adding it.
- Cache: every consumer's agent-CLI cache key changes once (the catalog gains `agent:kiro-cli`); later it changes only
  when a pin or an override of a CLI in use changes. Every cached probe result is probed again once after the upgrade
  (the probe's cache identity gains the effective pin).
- Ledger: `availability.selected.probes.<profile>.binary_pinned`, written only on a drift. Older readers ignore it.
- Behaviour change: in CI a present CLI of another version is replaced (before: kept when it met the floor). On a
  person's machine `l4 doctor --fix` no longer installs over a present CLI below the profile's `min_version`: the
  action is `manual` with the command (before: it installed the pin over it). A Kiro 3.x is refused. `prereqs.sh
  --apply` no longer updates Kiro to `latest`. A Claude Code that L4 starts never updates itself.
- Collides with `opencode-v2` (row 52, also 0.4.20) in the catalog, the doctor rows and `prereqs.sh`; design
  "Collisions" names the merge order.
- Spec: L4-PRV-042 to L4-PRV-046, L4-OCG-005, SCN-PRV-113 to SCN-PRV-128, SCN-OCG-11 to SCN-OCG-14, doctor ENV-015,
  change-table row 57.
- No new runtime dependency (`zipfile` is the standard library). No prompt version change.
