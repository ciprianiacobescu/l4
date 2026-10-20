## Purpose

Every agent CLI that L4 installs runs at a version L4 chose and tested: Kiro has a pin and a digest that ships with the
harness, the pin is exact where L4 installs in CI, no process L4 starts updates a CLI, a team can hold another version
of the same major, and doctor and the probe say which version runs against which pin.

## ADDED Requirements

### Requirement: L4-PRV-042 Kiro CLI is pinned and installed from its versioned archive
The provisioning catalog SHALL pin `kiro-cli` at `KIRO_VERSION = "2.32.0"` in `ADAPTER_PINS`, and `catalog_pins()`
SHALL list `agent:kiro-cli`, so the agent-CLI cache key (L4-ACT-002) changes with the pin. On Linux the harness SHALL
install Kiro from `https://prod.download.cli.kiro.dev/stable/<version>/kirocli-<arch>-linux.zip`, or
`…-linux-musl.zip` when the glibc version is below 2.34 on x86_64 or below 2.39 on aarch64 or no glibc is found. It
SHALL never download from `latest`, never download Kiro's installer script, and never fetch `manifest.json` or
`index.json` to install. The archive's sha256 SHALL be compared with the harness's table `KIRO_SHA256` (by version, then
by `linux-x64`, `linux-arm64`, `linux-x64-musl`, `linux-arm64-musl`), which holds the pin and the versions with recorded
fixtures (2.28.0, 2.27.1). A mismatch SHALL remove the archive, change nothing in `~/.local/bin`, and fail the action
naming both digests and the manual command; a download the CDN refuses (it answers 403 for a version it does not
serve) SHALL fail the action with the manual command. The harness SHALL extract exactly the members
`kirocli/bin/kiro-cli-term`, `kirocli/bin/kiro-cli-chat` and `kirocli/bin/kiro-cli`, each a regular file of at most 512
MiB, into `~/.local/bin` with mode 0755. It SHALL check all three members before it writes anything, stage each beside
its target and rename the three over their targets only when all three are staged, so a missing, linked or oversized
member or an error while staging removes the staged files and changes nothing in `~/.local/bin`. It SHALL extract
nothing else, run no file of the archive, and download into a temporary directory that is removed when the step ends.
After the install, `kiro-cli --version` on the harness path SHALL report the target version. On macOS the harness SHALL
install nothing: the Kiro action is `manual`, whether or not a `kiro-cli` is present, and names
`https://prod.download.cli.kiro.dev/stable/<version>/Kiro%20CLI.dmg` and its sha256.

#### Scenario: SCN-PRV-113 (+) doctor --ci --fix installs Kiro from the pinned archive
- **GIVEN** a `linux-x64` runner with glibc 2.39, no `kiro-cli`, a `kiro-cli` profile in a role chain, and a fetcher
  that serves the 2.32.0 archive whose sha256 equals the table's
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the only URL fetched for Kiro is `https://prod.download.cli.kiro.dev/stable/2.32.0/kirocli-x86_64-linux.zip`,
  `~/.local/bin` holds `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` with mode 0755 and no other new file, no file of
  the archive was run, the temporary directory is gone, and the action is `applied` with `kiro-cli 2.32.0`

#### Scenario: SCN-PRV-114 (−) An archive whose digest differs installs nothing
- **GIVEN** the same runner and a fetcher that serves an archive whose sha256 is not the table's
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the action is `failed` naming both digests and the manual command, the archive is removed, nothing under
  `~/.local/bin` changed, and doctor exits 3

#### Scenario: SCN-PRV-115 (+) The archive follows the architecture and the libc
- **GIVEN** a `linux-arm64` host with glibc 2.35, a `linux-x64` host with glibc 2.35, and a `linux-x64` host where
  no glibc version can be read
- **WHEN** the harness picks the Kiro archive for each
- **THEN** they get `kirocli-aarch64-linux-musl.zip`, `kirocli-x86_64-linux.zip` and `kirocli-x86_64-linux-musl.zip`,
  each checked against its own row of the table

#### Scenario: SCN-PRV-116 (−) A missing or linked archive member is never extracted
- **GIVEN** an archive whose digest matches a test table and that holds `kirocli/bin/kiro-cli-chat` as a symbolic link,
  another that has no `kirocli/bin/kiro-cli-term`, and a third whose `kirocli/bin/kiro-cli-chat` cannot be written
  while it is staged
- **WHEN** the harness installs each
- **THEN** each action fails naming the member, no file under `~/.local/bin` changed, no staged file is left, and for
  the first two no member was extracted

#### Scenario: SCN-PRV-117 (−) On macOS nothing is downloaded
- **GIVEN** a `darwin-arm64` machine with no `kiro-cli` and a `kiro-cli` profile in a role chain, and a second one
  whose `kiro-cli` prints `kiro-cli 2.27.1` for a profile whose `min_version` is `2.32.0`
- **WHEN** `l4 doctor --fix` runs
- **THEN** on both the `kiro-cli` action is `manual`, names `stable/2.32.0/Kiro%20CLI.dmg` and its sha256, and nothing
  was downloaded

#### Scenario: SCN-PRV-118 (+) The Kiro pin is part of the agent-CLI cache key
- **GIVEN** the provisioning catalog
- **WHEN** `catalog_pins()` and `catalog_hash()` are computed, and again with `KIRO_VERSION` set to another version
- **THEN** `catalog_pins()` holds `agent:kiro-cli` = `2.32.0`, and the two hashes differ

### Requirement: L4-PRV-043 The pin is exact where L4 installs in CI, and a person's fix keeps the floor rule
Under `l4 doctor --ci --fix`, a present agent CLI whose version is not its effective pin (L4-PRV-045) SHALL be `planned`
with the reason `found <found>, pinned <pin>` and installed at the pin: Claude Code by its installer with the pin, Codex
and OpenCode by `npm install --save-exact` into the harness prefix, Kiro from its archive (L4-PRV-042). After such an
install the CLI on the harness path SHALL report exactly the pin, else the action SHALL fail with `installed <found>,
but <pin> (pinned) is needed`. The L4-OCG-004 guard SHALL still keep a regular file at `~/.local/bin/opencode`; the
Kiro files in `~/.local/bin` SHALL be replaced whatever they are. When `ci.self_provision` resolves false every install
action SHALL stay `skipped`, as today. Without `--ci`, `l4 doctor --fix` SHALL keep today's floor rule: a present agent
CLI of the supported major that meets the `min_version` of its profiles (or whose profiles set none) SHALL be `already
present` and never replaced, while doctor ENV-015 (L4-PRV-046) warns with the installed and pinned versions and the
command; one below `min_version` SHALL be `planned` with `found <found>, need <min_version>` and installed at the pin
user-locally, as today; a `kiro-cli` of another major SHALL be `manual` with the reason and the command, never
`planned`, and its files SHALL stay unchanged; on macOS the Kiro action SHALL be `manual` (L4-PRV-042). An `opencode` of
another major SHALL still be replaced by the pinned v1 through its guarded link (L4-OCG-004). A missing CLI SHALL be
installed at the pin in both modes. `scripts/runner/prereqs.sh` PRQ-12 SHALL default `KIRO_VERSION` to the catalog pin
and carry the pin's four digests, which a test compares with the catalog. Its check SHALL pass only when `kiro-cli
--version` equals `KIRO_VERSION`. Its apply SHALL never run `kiro-cli update` or Kiro's installer script: it SHALL
download the versioned archive, check it with `sha256sum -c`, and install the three binaries with `install -m 755` into
the runner user's `~/.local/bin`.

#### Scenario: SCN-PRV-119 (+) In CI a present CLI of another version is replaced by the pin
- **GIVEN** `codex 0.161.0` on the harness path and a `codex` profile in a role chain
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the codex action is `planned` with `found 0.161.0, pinned 0.160.0`, npm installs `@openai/codex@0.160.0` into
  the harness prefix, and the action is `applied` with `codex 0.160.0`; when the installed CLI still reports
  `0.161.0` afterwards, the action is `failed` with `installed 0.161.0, but 0.160.0 (pinned) is needed` and doctor
  exits 3

#### Scenario: SCN-PRV-120 (−) On a person's machine a CLI that meets the floor is never replaced
- **GIVEN** a Linux machine with a regular file `~/.local/bin/kiro-cli` that prints `kiro-cli 2.33.0` and a `kiro-cli`
  profile in a role chain, and a second machine with `codex 0.150.0` and a `codex` profile whose `min_version` is
  `0.160.0`
- **WHEN** `l4 doctor --fix` runs without `--ci`
- **THEN** nothing is downloaded, the file is unchanged, the action is `already present`, and ENV-015 warns
  `kiro-cli 2.33.0 at ~/.local/bin/kiro-cli, pinned 2.32.0` with the command that installs the pin; on the second
  machine, as before this change, the codex action is `planned` with `found 0.150.0, need 0.160.0`, npm installs
  `@openai/codex@0.160.0` into the harness prefix, and the action is `applied` with `codex 0.160.0`

#### Scenario: SCN-PRV-121 (−) prereqs.sh pins Kiro and never updates it
- **GIVEN** `scripts/runner/prereqs.sh` and a runner user whose `kiro-cli --version` prints `kiro-cli 2.33.0`
- **WHEN** PRQ-12 checks, and its apply function is read
- **THEN** the check reports MISSING with `pinned 2.32.0`; the script holds no `kiro-cli update` and no
  `cli.kiro.dev/install`; the apply downloads `stable/$KIRO_VERSION/` and runs `sha256sum -c`; and `KIRO_VERSION` and
  the four digests equal the catalog's

### Requirement: L4-PRV-044 No process that L4 starts updates an agent CLI
The harness SHALL start each agent CLI with the self-update switch that CLI offers. Claude Code SHALL get
`DISABLE_AUTOUPDATER=1` and `DISABLE_UPDATES=1` in the environment of every run (implementer, judge, clarifier,
readiness review) and every probe step, the `binary` step included. Every installer the harness runs and every
`--version` read of `claude` by provisioning or doctor SHALL get `DISABLE_AUTOUPDATER=1` and never `DISABLE_UPDATES`,
which blocks `claude install`. Every `codex exec` argv (implementer, judge, hello) SHALL hold
`-c check_for_update_on_startup=false`; `codex app-server` gets none. OpenCode SHALL keep `OPENCODE_DISABLE_AUTOUPDATE=1`
and `"autoupdate": false` in every run and probe. Every private `KIRO_HOME` the harness writes SHALL hold
`settings/cli.json` with `app.disableAutoupdates` true: an implementer step's holds only that key, and a judge's, a
hello's and a listing's keep the four judge settings. A Kiro call without a private `KIRO_HOME` (the `whoami` and
`/usage` probe steps, a read-only step, an implementer with `options.agent`) reads the runner user's settings.
`scripts/runner/prereqs.sh` PRQ-21 SHALL set, for the runner user, `env.DISABLE_AUTOUPDATER` = `"1"` in
`~/.claude/settings.json` and, when Kiro is installed, `app.disableAutoupdates` = true in `~/.kiro/settings/cli.json`,
each merged with `jq` (every other key kept, a missing file created, a file that is not JSON left untouched and
reported FAILED), without running an agent CLI. It SHALL never write `DISABLE_UPDATES` there.

#### Scenario: SCN-PRV-122 (+) A Claude Code that L4 starts never updates itself
- **GIVEN** a `claude-code` profile, and a host environment that sets `DISABLE_UPDATES=1`
- **WHEN** the harness builds the environment of an implementer run, of a judge run, of the probe's `binary`, `auth`
  and `hello` steps, and of `doctor --fix`'s Claude installer
- **THEN** the first five hold `DISABLE_AUTOUPDATER=1` and `DISABLE_UPDATES=1`, and the installer's holds
  `DISABLE_AUTOUPDATER=1` and no `DISABLE_UPDATES`

#### Scenario: SCN-PRV-123 (+) Kiro, Codex and OpenCode start with updates off
- **GIVEN** a `kiro-cli` implementer step without `options.agent`, a `kiro-cli` judge, a `codex` implementer, judge and
  hello, and an `opencode` run
- **WHEN** the harness writes their private `KIRO_HOME` and builds their argv and environment
- **THEN** the implementer's `settings/cli.json` is exactly `{"app.disableAutoupdates": true}`, the judge's holds the
  four judge settings, every `codex exec` argv holds `-c check_for_update_on_startup=false`, and the opencode
  environment keeps `OPENCODE_DISABLE_AUTOUPDATE=1`

#### Scenario: SCN-PRV-124 (+) PRQ-21 turns self-update off on the runner without touching other settings
- **GIVEN** a runner user whose `~/.claude/settings.json` is `{"model": "m", "env": {"FOO": "1"}}`, who has `kiro-cli`
  and no `~/.kiro/settings/cli.json`
- **WHEN** `prereqs.sh --apply` runs PRQ-21
- **THEN** the Claude file holds `model` `m`, `env.FOO` `1` and `env.DISABLE_AUTOUPDATER` `1` and no `DISABLE_UPDATES`,
  `~/.kiro/settings/cli.json` is `{"app.disableAutoupdates": true}`, no agent CLI ran, and a settings file that is not
  JSON is left as it was with PRQ-21 FAILED

### Requirement: L4-PRV-045 A repository holds another version with ci.cli_versions
The configuration key `ci.cli_versions` (default `{}`) SHALL map an agent CLI adapter (`claude-code`, `codex`,
`kiro-cli`, `opencode`) to an exact version `N.N.N` that replaces the catalog pin for that repository. The load SHALL
fail (exit 2), naming the key, for an unknown adapter, for a value that is not `N.N.N`, and for a version whose major
differs from the adapter's supported major (L4-OCG-001, L4-OCG-005), with the text `… is <product> <major>; this
harness runs <product> <supported> (L4-OCG-001, L4-OCG-005); a major moves with an L4 release, not with configuration`.
The effective pin (the override, else the catalog's) SHALL be what provisioning installs and compares (L4-PRV-043),
what the probe and doctor report (L4-PRV-046), and part of the agent-CLI cache key (L4-ACT-002) for the adapters in
use. A Kiro override SHALL be installed only when `KIRO_SHA256` holds that version for the platform; otherwise its
action SHALL be `manual` before any download, naming the versions the table holds, and a `kiro-cli` already present
keeps running with ENV-015's warning. An override below a profile's `min_version` SHALL leave the action `skipped` by
the floor rule of L4-DOC-002 (a floor above the pin). Doctor ENV-015 SHALL name every override and the catalog pin it
replaces.

#### Scenario: SCN-PRV-125 (+) A repository holds kiro-cli at 2.28.0
- **GIVEN** `ci.cli_versions` `{kiro-cli: "2.28.0"}` with a `kiro-cli` profile in a role chain, and `kiro-cli 2.32.0`
  on a `linux-x64` runner
- **WHEN** `l4 ci cache-key clis` runs, then `l4 doctor --ci --fix`
- **THEN** the key differs from the key without the override, the action is `planned` with `found 2.32.0, pinned
  2.28.0 (ci.cli_versions)`, the 2.28.0 archive is checked against the table's 2.28.0 digest, and ENV-015 then passes
  naming `kiro-cli 2.28.0 held by ci.cli_versions; L4 pins 2.32.0`

#### Scenario: SCN-PRV-126 (−) An override never crosses the major gate
- **GIVEN** `ci.cli_versions` `{kiro-cli: "3.0.0"}`, and in turn `{opencode: "2.0.32"}`
- **WHEN** the configuration loads
- **THEN** it fails with exit 2 and `ci.cli_versions: kiro-cli: 3.0.0 is Kiro CLI 3; this harness runs Kiro CLI 2
  (L4-OCG-001, L4-OCG-005); a major moves with an L4 release, not with configuration`, and the same form for OpenCode

#### Scenario: SCN-PRV-127 (−) An unknown adapter, a malformed version, and a Kiro version without digests
- **GIVEN** `ci.cli_versions` `{gemini: "1.0.0"}`, then `{codex: "latest"}`, then `{kiro-cli: "2.31.1"}` on a
  `linux-x64` runner with no `kiro-cli`
- **WHEN** the configuration loads and `l4 doctor --ci --fix` runs
- **THEN** the first two fail the load naming the key, and the third loads, its action is `manual` with `has no sha256
  in this harness (it holds 2.27.1, 2.28.0, 2.32.0)`, nothing was downloaded, and ENV-004 fails for the missing
  `kiro-cli` as for any missing CLI; with `kiro-cli 2.32.0` present instead, the action is the same, ENV-015 warns
  naming 2.31.1 and 2.32.0, and doctor exits 0

### Requirement: L4-PRV-046 Doctor and the probe report the installed version against the pin
The probe's passing `binary` step SHALL record `pin` and `pin_source` (`catalog` or `ci.cli_versions`) for every
adapter with a pin, and `major` for every gated adapter. The probe's cache identity SHALL include the effective pin, so a
changed override is never answered from the cache. The probe line SHALL read `binary <found> (pinned <pin>)` when they
differ and stay `binary <found>` when they are equal, and `l4 probe --json` SHALL carry the detail.
`availability.selected` SHALL record `probes.<profile>.binary_pinned` when the version differs from the pin, and only
then. Doctor ENV-015 (warn) SHALL report, for each agent CLI a role chain uses, its version on the harness path against
its effective pin: a pass names the versions and the overrides, a failure names each CLI, its path, both versions and
the fix (`l4 doctor --ci --fix` in CI, the manual command on the machine). A missing CLI or a wrong major is left to
ENV-004. `l4 doctor --ci --fix` SHALL apply the install fix to ENV-015 as it does to ENV-004.

#### Scenario: SCN-PRV-128 (+) The probe, its line and the ledger name a drift
- **GIVEN** a `kiro-cli` profile and a `kiro-cli` on PATH that prints `kiro-cli 2.33.0`, pinned 2.32.0
- **WHEN** `l4 probe --json` runs, the line is printed, and the profile is selected for a role
- **THEN** the `binary` step passes with `version` `2.33.0`, `pin` `2.32.0`, `pin_source` `catalog` and `major` 2, the
  line reads `binary 2.33.0 (pinned 2.32.0)`, and `availability.selected` holds `binary_pinned` `2.32.0`; with
  `kiro-cli 2.32.0` the line reads `binary 2.32.0` and the event holds no `binary_pinned`
