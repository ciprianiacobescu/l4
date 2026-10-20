## Context

The owner's intent: every agent CLI that L4 installs runs at a version L4 chose and tested. This change gives Kiro a
pin, makes the pin exact where L4 installs in CI, turns self-update off, gates kiro-cli 3, lets a consumer hold another
version, and reports installed against pinned. It is built for 0.4.20 on the 0.4.19 release candidate (1572bf6e).

Labels: [V] verified (in the code at 1572bf6e, in a file read, or by a request made on 2026-10-20); [D] the vendor's
documentation; [I] inferred; [U] unknown until recorded. No agent CLI was run for this design and no install was made.

### What the code does today [V]

- `src/l4/provision/catalog.py`: `CLAUDE_VERSION = "2.1.288"`, `CODEX_VERSION = "0.160.0"`, `OPENCODE_VERSION =
  "1.18.34"` in `ADAPTER_PINS`; `INSTALLER_URLS["kiro-cli"] = "https://cli.kiro.dev/install"`; `catalog_pins()` "Kiro and
  bwrap have no pin"; `catalog_hash` is the suffix of the agent-CLI cache key (L4-ACT-002); `SUPPORTED_MAJORS` holds
  only `opencode`, and `major_problem` builds an OpenCode sentence; `manual_command` for Kiro is `curl -fsSL
  https://cli.kiro.dev/install | bash`.
- `src/l4/provision/runner.py`: `is_satisfied` for an agent is "not a wrong major, and `min_version is None or found >=
  min_version`"; `plan_fixes` marks a satisfied tool `already present`, a floor above the pin `skipped`, else `planned`.
- `src/l4/provision/install.py`: `_install_agent` runs the saved Kiro installer with `bash` and no argument; Claude's
  installer gets the pin as its argument; Codex and OpenCode are `npm install --save-exact <pkg>@<pin>` into
  `$L4_HOME/npm`, linked into `~/.local/bin`. `_verified` and `plan_fixes` word a wrong major as OpenCode.
- `src/l4/availability/probes.py` `_binary`: reads `--version`, records `version`, gates the major for adapters in
  `SUPPORTED_MAJORS`, then compares `min_version`. `probe_claude` adds only `CLAUDE_CODE_MAX_RETRIES` (and the credential
  variable) to `probe_env`, which passes the real `HOME`.
- `src/l4/agents/claude_code.py`: `extra_env` = `CLAUDE_CODE_MAX_RETRIES`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY`.
  `src/l4/agents/codex.py`: `codex exec … --ignore-user-config --ignore-rules -c project_doc_max_bytes=0`.
  `src/l4/agents/opencode.py`: `OPENCODE_DISABLE_AUTOUPDATE=1` and `"autoupdate": false` in every run and probe.
- `src/l4/agents/kiro_cli.py`: `JUDGE_SETTINGS` = `chat.disableInheritingDefaultResources`, `chat.agentEngine: v2`,
  `chat.enableAutoAgentUpgrade: false`, `app.disableAutoupdates: true`, written to the private `KIRO_HOME` of a judge,
  a hello and the model listing. `write_harness_agent` (an implementer step without `options.agent`) writes the agent
  file only. A read-only step and an implementer with `options.agent` set no `KIRO_HOME`.
- `scripts/runner/prereqs.sh`: `KIRO_VERSION=${KIRO_VERSION:-2.28.0}` "floor, not an exact pin"; `check_kiro` is
  `ver_ge`; `apply_kiro` runs `kiro-cli update --non-interactive` over an existing install, else the installer.
  `check_claude` and `check_codex` compare exactly; `check_opencode` is a major-1 floor.
- `.github/actions/l4/action.yml`: the agent-CLI cache holds `~/.local/bin` (without `uv`, `uvx`, `l4`,
  `laya-serve`), `~/.local/share/l4` (without Laya), `~/.local/share/claude` and `~/.cache/l4/installers`. The workflow
  templates save it right after the `doctor` step, before `plan` and `run` (`l4.github-action.yml`: `@@CLIS_SAVE@@`
  follows `doctor`).
- `tests/fixtures/recorded/kiro-cli/` holds 2.27.1, 2.28.0 and 2.32.0; `version.stdout.txt` of 2.32.0 is `kiro-cli
  2.32.0`. L4's live Kiro-judge tests passed on 2.32.0 on GitHub-hosted `ubuntu-24.04` on 2026-10-20
  (`docs/live/kiro-judge/README.md`), where `settings list` read the four judge settings from `KIRO_HOME` as `(global)`.

### Kiro's distribution [V, 2026-10-20]

- The installer (`https://cli.kiro.dev/install`) takes only `--channel` (default `stable`) and `--force`. On Linux it
  downloads `<base>/<channel>/latest/kirocli-<arch>-linux.zip`, or `…-linux-musl.zip` when glibc is below 2.34 on
  x86_64 or below 2.39 on aarch64 (or is not found), with `<base>` = `https://prod.download.cli.kiro.dev`; on macOS
  `latest/Kiro CLI.dmg`. It verifies sha256 against `<channel>/latest/manifest.json` fetched in the same run. Over an
  existing `~/.local/bin/kiro-cli` it asks "Do you want to replace it? (y/N)" on `/dev/tty`.
- Versioned files are served: HEAD `stable/2.32.0/kirocli-x86_64-linux.zip` → 200, 154,980,622 bytes (the `size` the
  index gives); `stable/2.32.0/kirocli-aarch64-linux-musl.zip` → 200, 151,681,117 bytes; `stable/2.32.0/Kiro%20CLI.dmg`
  → 200, 348,674,736 bytes. Per-version `manifest.json` paths answer 403.
- `https://prod.download.cli.kiro.dev/stable/index.json` (1.4 MB) lists 176 versions, newest first, each package with
  `download` (`<version>/<file>`), `sha256` and `size`. Its 24 packages of 2.32.0 equal `stable/latest/manifest.json`'s.
- The archive (2.32.0 x86_64 gnu, read through HTTP range requests of its central directory and of three small
  members; 76 kB fetched): `kirocli/README`, `kirocli/BUILD-INFO` (`BUILD_VERSION=2.32.0`,
  `BUILD_TARGET_TRIPLE=x86_64-unknown-linux-gnu`), `kirocli/install.sh`, and `kirocli/bin/` with `kiro-cli`
  (43,931,168 bytes), `kiro-cli-chat` (207,496,744), `kiro-cli-term` (34,060,512), and two 2-line shell wrappers `q` and
  `qchat` that call `"$HOME/.local/bin/kiro-cli"`. The archive's `install.sh`, user mode: checks the target triple and
  glibc, then `install -m 755` of `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` into `$HOME/.local/bin/`, then
  `kiro-cli setup` unless `KIRO_CLI_SKIP_SETUP` is set (the outer installer sets it). No prompt; it overwrites.
- Kiro's settings page: `app.disableAutoupdates` "Disable background auto-updates"; settings live in
  `~/.kiro/settings/cli.json`, a workspace `.kiro/settings/cli.json` overrides the global value, and "In V3, [`KIRO_HOME`]
  overrides the global Kiro directory for configuration, sign-ins, sessions, and agent state" [D]. No environment
  variable turns updates off [D: none listed].
- Kiro 2.32.0 has no public release notes. Its `chat --help` names `--agent-engine … "v2" (default)` and `--v2 Use the
  V2 agent engine (the pre-3.0 default)` [V, kiro-judge R13 and 2026-10-20].

### Self-update switches [D unless marked]

| CLI | Switch | Source |
|---|---|---|
| Claude Code | `DISABLE_AUTOUPDATER=1`: "disable automatic background updates. Manual `claude update` still works". `DISABLE_UPDATES=1`: "block all updates including manual `claude update` and `claude install` … Use when distributing Claude Code through your own channels". The `env` key of `settings.json` sets either. | code.claude.com env-vars and setup pages |
| Codex | config key `check_for_update_on_startup` (boolean): "Check for Codex updates on startup (set to false only when updates are centrally managed)". No environment variable found. Whether 0.160.0 knows the key is [U]. An npm install in the harness prefix is not replaced by Codex itself [I]. | the Codex config reference |
| OpenCode | `OPENCODE_DISABLE_AUTOUPDATE=1` and `"autoupdate": false` | [V code], already set |
| Kiro CLI | setting `app.disableAutoupdates: true` in `<KIRO_HOME>/settings/cli.json` or `kiro-cli settings app.disableAutoupdates true`. Read from `KIRO_HOME` [V, live run 1]; that the CLI acts on it [I]. Whether a Linux zip install updates itself in the background at all [U]. | kiro.dev settings page |

## Goals / Non-goals

Goals: every agent CLI that L4 installs is installed at its pin, Kiro included, and a Kiro download is trusted only
through digests that ship with the harness. In CI a CLI of another version is replaced; on a person's machine it is
reported, never replaced. No process that L4 starts updates a CLI. A kiro-cli 3 is refused by name. A team can hold
another version of the same major by configuration. Doctor and the probe say which version runs and which is pinned.

Non-goals:
- Kiro CLI 3 support (a later change, after its streams are recorded; L4-FAC-007 already says the 2.32.0 shapes are
  re-recorded before the pin moves to 3.x).
- Digests in the harness for Claude Code, Codex or OpenCode. Their trust anchors stay as today: Claude's installer and
  npm's registry integrity.
- Major gates for Claude Code or Codex (L4-OCG-001's note stands: a separate decision with its own evidence).
- A per-version install directory that lets two harness releases share one runner user without replacing each other's
  CLIs (Open question 1).
- An automatic install of Kiro on macOS (D4).

## D1. The Kiro pin and its archive (L4-PRV-042)

Decision: `KIRO_VERSION = "2.32.0"` joins `ADAPTER_PINS`. `INSTALLER_URLS["kiro-cli"]` is removed: the harness no
longer downloads Kiro's installer script. It downloads the archive itself:

```
KIRO_DOWNLOAD = "https://prod.download.cli.kiro.dev/stable"
kiro_archive_url(version, platform) -> f"{KIRO_DOWNLOAD}/{version}/kirocli-{arch}-linux{musl}.zip"
#   arch: linux-x64 -> x86_64, linux-arm64 -> aarch64; musl: "-musl" for the *-musl platform keys
```

The digest comes from `KIRO_SHA256: dict[str, dict[str, str]]` in the catalog, keyed by version, then by platform key
(`linux-x64`, `linux-arm64`, `linux-x64-musl`, `linux-arm64-musl`). It holds the pin and the two versions with
recorded fixtures, so that a team can hold one of them (D9). Values from `stable/index.json` on 2026-10-20 (the 2.32.0
row equals `stable/latest/manifest.json`) [V as published; recomputed over the bytes by task 1.1]:

| version | `linux-x64` | `linux-arm64` | `linux-x64-musl` | `linux-arm64-musl` |
|---|---|---|---|---|
| 2.32.0 | `7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb` | `f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848` | `f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485` | `219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b` |
| 2.28.0 | `4d6d20c3ffed99904081a062678b3c1978dc7d68c9f6c530f3f28f163011c8ee` | `39169fc43557ff3c007ccf5388ff95413539b2c6a8dfab6c69e4a7b8899bebbc` | `8ee7e1b789af4d506ebd661fe4a2d88a1cf20b4027170aae7c3cd1daf348b98c` | `c91fb5b7bec67acbbe0cdbc239f7a6b8e541f6bff2db32e418b0e3090f5e38b2` |
| 2.27.1 | `e68927fe0bffb752746a573010cb68792b0f3e97be3a6ce73792c9cc02f08007` | `abdb1f8167693f34163c1b053ccdce4819e191140e9319a0c78c55c252b11d83` | `7c7a9f5e3284c82cc6f0fb1a301597368538adb83d916927e664c957a9f953ef` | `937ff1ae3df373717b66cc09aec79c3b7f0b8e53968d746e3a4545722e1e4587` |

`KIRO_DMG_SHA256` (shown, never used by an install, D4): 2.32.0 `88721f97dbe98c9e4f84a46e8a2584a8dd29289b81264d96ee2987dd2c014e3c`,
2.28.0 `5119dfebf8234d336af874af631d1039e3b9a9bbd6da1c71874f5855173a91c8`, 2.27.1
`850da13e0667f5bc4ef645526b5ba08a50dc8442cd92bad1ffc7546a7ce8195c`.

The harness never reads `latest/` and never fetches `manifest.json` or `index.json` to install. `index.json` is read only
by `scripts/kiro_pin.py` (D11), a maintenance script that prints the table rows for a version, and by no test that
runs offline.

Why: an installer that resolves `latest` and verifies against a manifest fetched in the same request chain proves that
the file is what the vendor serves today, not that it is the file L4 tested. The archive URL with a version is served
[V], so the pin can be exact, and a digest that ships with the harness is the only anchor that a changed `latest` cannot
move. The zip is the file the vendor's installer uses, so the content is the same as a vendor install.

`catalog_pins()` gains `agent:kiro-cli: 2.32.0`, so `catalog_hash` and every consumer's agent-CLI cache key change once
with this release, and again whenever the Kiro pin moves. The digests are not hashed into the key: the version names
them.

## D2. Where Kiro goes: the vendor's layout, without the vendor's script (L4-PRV-042)

Decision: `_install_kiro(ctx, tool)`:
1. `platform = kiro_platform(ctx.platform)` (D3); `expected = KIRO_SHA256[version][platform]` (a missing entry never
   reaches here: `plan_fixes` made the action `manual`, D9).
2. Download the archive with the context's `Fetcher` into a `tempfile.TemporaryDirectory(prefix="kiro-",
   dir=ctx.downloads)`, so the 155 MB file is gone when the step ends and never lands in `~/.cache/l4/installers`,
   which the agent-CLI cache saves.
3. `verify_sha256(archive, expected)`: a mismatch removes the file and raises `IntegrityError`; the action is `failed`
   with both digests and the manual command, and nothing under `~/.local/bin` has changed.
4. Open it with `zipfile.ZipFile`. Extract exactly the members `kirocli/bin/kiro-cli-term`, `kirocli/bin/kiro-cli-chat`
   and `kirocli/bin/kiro-cli`, by those names and in that order, nothing else. Each must exist, be a regular file (the
   Unix mode in `external_attr >> 16` is `S_IFREG`, not a link) and be at most 512 MiB uncompressed; otherwise the
   action fails naming the member. Each is streamed to `~/.local/bin/.<name>.tmp.<pid>`, given mode 0o755 and moved
   onto `~/.local/bin/<name>` with `os.replace`. The archive's `install.sh`, `q`, `qchat`, `README` and `BUILD-INFO`
   are not extracted and no file of the archive is run.
5. `_verified` reads `kiro-cli --version` from the harness path; it must be the target version (D5), else the action
   fails naming the path and both versions.

Why the vendor's layout (three regular files in `~/.local/bin`) and not a versioned directory with links: the
archive's own `install.sh` puts exactly these three files there [V], the `q` and `qchat` wrappers call
`$HOME/.local/bin/kiro-cli` [V], and how `kiro-cli` finds `kiro-cli-chat` through a symlink is [U]. The agent-CLI
cache already saves `~/.local/bin` [V], so nothing in the action changes. Why not run the archive's `install.sh`: it is
code from a download, and without `KIRO_CLI_SKIP_SETUP` it runs `kiro-cli setup` (shell integrations, dotfiles) [V];
its only other effect is the three copies, which the harness does itself.

`zipfile` has no `filter="data"`; the member allow-list by exact name is the whole defence, and no member name from the
archive becomes a path.

## D3. gnu or musl (L4-PRV-042)

Decision: `kiro_platform(platform: str, libc: str | None = <read>) -> str`. On `linux-x64` it is `linux-x64` when the
glibc version is at least 2.34, on `linux-arm64` it is `linux-arm64` when it is at least 2.39, and otherwise the
`-musl` key; on any other platform it raises `ValueError` (D4). The glibc version is `os.confstr("CS_GNU_LIBC_VERSION")`
(`"glibc 2.39"`); a `ValueError`, `OSError` or `None` there means no glibc, which is musl. The thresholds are the
vendor's [V: both install scripts]. `os.confstr` answering on a glibc system is [I]; a musl system's answer is [U], and
both are stubbed in the tests.

Why: the gnu build refuses to install below those glibc versions [V: the archive's `install.sh`]. GitHub's
`ubuntu-24.04` image has glibc 2.39 and `ubuntu-22.04` 2.35 [I], so x86_64 gets gnu on both and arm64 gets musl on
22.04.

## D4. macOS: no automatic install (L4-PRV-042)

Decision: on `darwin-*` the Kiro action is `manual` and nothing is downloaded. `manual_command` names:
`download https://prod.download.cli.kiro.dev/stable/2.32.0/Kiro%20CLI.dmg, check it with shasum -a 256 (88721f97…
full digest), open it and copy Kiro CLI.app to /Applications (this replaces an installed Kiro CLI)`. Doctor's ENV-004
and ENV-015 lines carry the same text.

Why: the macOS install mounts a disk image, copies an app bundle into `/Applications`, asks on `/dev/tty` before
replacing one and starts the app [V: the installer]. That is a person's decision on a person's machine, and L4 runs
agent steps on Linux only (bubblewrap), so a Mac never needs the pin for `l4 run`.

## D5. Exact in CI, never silent on a person's machine (L4-PRV-043)

Decision:
- `ToolSpec.version` of an agent is its effective pin (D9). `is_satisfied(tool, found, *, exact: bool = False)`: an
  agent of a wrong major is never satisfied (as today); with `exact`, an agent is satisfied only when
  `parse_version(found) == parse_version(tool.version)`; without, today's floor rule holds.
- `plan_fixes` and `install_planned` gain `replace_present: bool = False`, passed to `is_satisfied` as `exact`.
  `DoctorContext` gains `ci: bool = False`, set from `l4 doctor --ci`; `fix_provision` and `survey_provision` pass
  `replace_present=ctx.ci`. Every generated CI file runs `l4 doctor --ci --fix` or `l4 doctor --ci` [V templates], so
  "CI" is exactly `--ci`.
- Under `--ci --fix`, a present agent CLI of another version is `planned` with the reason `found <found>, pinned <pin>`
  (`<pin> (ci.cli_versions)` for an override) and installed as for a missing one: Claude's installer with the pin,
  `npm install --save-exact <pkg>@<pin>` into the harness prefix, the Kiro archive (D2). L4-OCG-004's guard stays as it
  is: a regular file at `~/.local/bin/opencode` is never replaced. The Kiro files at `~/.local/bin` are replaced
  whatever they are: they are the vendor's layout, and in CI they belong to the runner.
- Without `--ci`, a present agent CLI of the supported major is never replaced: it is `already present`, and ENV-015
  (D10) warns with both versions and the command. A present `kiro-cli` of a wrong major is `manual` with the reason
  and the command, never `planned` (its files are regular files a person may own). A present `opencode` of a wrong
  major keeps L4-OCG-004's local behaviour (the harness prefix and a guarded link). A missing CLI is installed at the
  pin, as today.
- `_floor_above_pin` and the profile's `min_version` keep their meaning.

Why `--ci` and not `ci.self_provision`: `self_provision` resolves true on a person's machine too (`auto` is true on
local runs [V L4-DOC-002]), so it cannot tell a runner from a laptop; `--ci` is what every CI file passes and what a
person does not.

## D6. prereqs.sh PRQ-12 (L4-PRV-043, L4-OCG-005)

Decision: the top block gets `KIRO_VERSION=${KIRO_VERSION:-2.32.0}` (the comment "floor, not an exact pin" goes) and
four digests, the pin's row of D1: `KIRO_SHA256_X86_64`, `KIRO_SHA256_AARCH64`, `KIRO_SHA256_X86_64_MUSL`,
`KIRO_SHA256_AARCH64_MUSL`, each `${NAME:-<digest>}`. `check_kiro` passes only when the runner user's `kiro-cli
--version` equals `KIRO_VERSION`; its DETAIL names the found version, the path and `pinned $KIRO_VERSION`, and a major
other than 2 adds `Kiro CLI <major>; L4 runs Kiro CLI 2`. `apply_kiro` never runs `kiro-cli update` and never the
installer script: as the runner user it picks `x86_64` or `aarch64` from `uname -m` and gnu or musl by `ldd --version`
with D3's thresholds, downloads `https://prod.download.cli.kiro.dev/stable/$KIRO_VERSION/kirocli-<arch>-linux[-musl].zip`
into a `mktemp -d` under the runner user's home, checks it with `sha256sum -c` against the matching digest, unzips it,
and runs `install -m 755` for `kiro-cli-term`, `kiro-cli-chat` and `kiro-cli` into `~/.local/bin`. A `KIRO_VERSION`
set without its digests fails at `sha256sum -c` with a DETAIL that says to set the four `KIRO_SHA256_*`. A drift test
compares `KIRO_VERSION` and the four digests with the catalog. The `--without-kiro` switch stays.

Why `install -m 755` in the script and not the archive's `install.sh`: the same reason as D2; the three lines are what
that script does [V].

## D7. Self-update off (L4-PRV-044)

Decision, per CLI, for every process the harness starts to make a model call or a login check (runs, judges,
clarifiers, readiness reviews, every probe step); a `--version` read starts no update [I] and gets nothing:
- Claude Code: `ClaudeCodeAdapter.extra_env` and `probe_claude`'s `probe_env` extra gain `DISABLE_AUTOUPDATER=1` and
  `DISABLE_UPDATES=1`. Both, because `DISABLE_UPDATES` is the documented switch for "your own channels" [D] and whether
  2.1.288 knows it is [U], while `DISABLE_AUTOUPDATER` is the older one [I]. Neither is ever added to an installer's
  environment: `scrub_env` is an allow-list [V code], and `DISABLE_UPDATES` would block `claude install` [D], which the
  native installer may run [I].
- Codex: every `codex exec` argv (implementer, judge, hello) gains `-c check_for_update_on_startup=false` after
  `-c project_doc_max_bytes=0`. The key is documented [D]; whether 0.160.0 accepts it is [U], so task 3.1 checks first
  that the pinned binary does not refuse it (an isolated `HOME` and `CODEX_HOME`, no credential: a refused key is a
  configuration error before any login check). A refusal stops the task and goes to the orchestrator; the switch is not
  dropped silently. `codex app-server` (the auth and quota probe) gets nothing: it is not the interactive client that
  checks [I].
- OpenCode: unchanged (`OPENCODE_DISABLE_AUTOUPDATE=1`, `"autoupdate": false`) [V].
- Kiro: `write_harness_agent` also writes `settings/cli.json` = `{"app.disableAutoupdates": true}`, only that key (the
  judge's other keys would change what an implementer inherits). The judge, the hello and the listing keep
  `JUDGE_SETTINGS`. A read-only step and an implementer with `options.agent` run without a private `KIRO_HOME`
  (today's K5 gap), so they read the runner user's settings: PRQ-21 sets the key there on a self-hosted runner, and on
  a disposable runner D10's exact check at the start of the next job is the guard.
- The runner image: `prereqs.sh` PRQ-21 "agent CLI self-update off" (PRQ-20 is taken by `opencode-v2`). Check: the
  runner user's `~/.claude/settings.json` has `.env.DISABLE_AUTOUPDATER == "1"` (read with `jq`, which PRQ-02 installs),
  and, with Kiro, `kiro-cli settings list` shows `app.disableAutoupdates` true. Apply: merge `{"env":
  {"DISABLE_AUTOUPDATER": "1"}}` into that file with `jq` (every other key kept; a missing file is created; a file that
  is not JSON is left untouched and the step is FAILED), and run `kiro-cli settings app.disableAutoupdates true` as
  the runner user. Only `DISABLE_AUTOUPDATER`, never `DISABLE_UPDATES`, in the image: PRQ-09 runs Claude's installer
  as the same user. OpenCode needs nothing there (every run gets an empty `XDG_CONFIG_HOME` and the switches) and
  Codex has no self-update of the harness prefix [I].

Why: a probe runs `claude` with the real `HOME` [V], and a native Claude install updates itself in the background
[D], so on a persistent runner the harness's own probe could move the version it then runs. A human's interactive
login on the runner (PRQ-15's instructions) starts the same CLIs, hence PRQ-21. On a GitHub-hosted runner the
agent-CLI cache is saved right after `doctor`, before any agent runs [V template order], so even a CLI that updated
itself later in the job cannot put another version into the cache under the pin's key.

## D8. The kiro-cli major gate (L4-OCG-005)

Decision: `SUPPORTED_MAJORS = {"opencode": 1, "kiro-cli": 2}`, each derived from its pin as today. `major_problem`
takes its wording from a per-adapter table, so the OpenCode sentence is unchanged and Kiro's is:

`kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli 2.32.0 (in CI l4 doctor --ci --fix installs it;
l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 release`

with the found version and the effective pin filled in. The `plan_fixes` reason (`found 3.0.0 (Kiro CLI 3), need
kiro-cli 2.x (pinned 2.32.0)`) and the `_verified` text (`kiro-cli at <path> reports 3.0.0 (Kiro CLI 3) after the
install, need kiro-cli 2.x (pinned 2.32.0)`) come from the same table. Every caller of L4-OCG-001/002 applies it: the
probe `binary` step (fails, no `auth`, `quota` or `hello`), ENV-004 (whether or not `min_version` is set), LIVE-005
(error, before the recorded-version comparison), `doctor --fix` (D5) and PRQ-12 (D6).

Why: Kiro CLI 3 changes the default engine [D], `--v2` has no documented future beyond "applies to that launch only"
[D], the judge refuses a stream on another engine [V], and in V3 `KIRO_HOME` also moves the sign-ins [D], so the
private `KIRO_HOME` of a judge could run with no login [I]. None of 3.x is recorded. A refusal at the free `binary` step
costs nothing and names the fix; a run that failed later would cost credits and read as something else.

## D9. The override `ci.cli_versions` (L4-PRV-045)

Decision: `CiCfg.cli_versions: dict[str, str] = {}`, beside `ci.toolchains`, read like every config key from
`.l4/config.yaml`:

```yaml
ci:
  cli_versions:
    kiro-cli: "2.28.0"
```

Validation at load (a `ValueError` the loader turns into exit 2), each message naming the key:
- a key that is not an adapter of `ADAPTER_PINS` (`claude-code`, `codex`, `kiro-cli`, `opencode`): `ci.cli_versions:
  unknown agent CLI <key> (one of claude-code, codex, kiro-cli, opencode)`;
- a value that is not `N.N.N`: `ci.cli_versions: <key>: <value> is not a version N.N.N`;
- for an adapter in `SUPPORTED_MAJORS`, a value of another major: `ci.cli_versions: <key>: <value> is <product>
  <major>; this harness runs <product> <supported> (L4-OCG-001, L4-OCG-005); a major moves with an L4 release, not with
  configuration`. An override never crosses the gate.

`effective_pins(cfg) -> dict[str, tuple[str, str]]` gives each adapter its version and its source (`catalog` or
`ci.cli_versions`). It feeds `required_tools` (`ToolSpec.version`), the reasons of D5 and D8, `ProbeCtx.pins` (D10),
ENV-015 and `clis_cache_hash(cfg)`: `catalog_hash(adapters, overrides)` adds `"overrides": {adapter: version}` for the
overrides of the adapters in use, only when there is one, so a config without an override keeps the catalog's key and
an override of a CLI that no role chain uses changes nothing.

A Kiro override is installed only when `KIRO_SHA256` holds that version for the platform (today 2.32.0, 2.28.0,
2.27.1). For any other version, `plan_fixes` marks the action `manual` before any download: `kiro-cli <v>
(ci.cli_versions) has no sha256 in this harness (it holds 2.27.1, 2.28.0, 2.32.0): install it yourself and keep it, or
hold one of those`. The load accepts such a value, so a self-hosted runner whose person installed that version can
declare it and is not replaced. Claude Code, Codex and OpenCode accept any version of the supported major (their
installers keep today's anchors). An override that equals the catalog pin is noted by ENV-015 (`… remove it`).

Why a config key and not an environment variable: the version a repository's agents run is a property of the
repository, it must reach `l4 ci cache-key clis` (which reads the config [V]), and a strict schema validates it. Why
one map: one binary per machine serves every profile of an adapter, so a per-profile version would be ambiguous.
Note for kiro-judge: CFG-011 already warns when a Kiro judge may run below 2.32.0 (L4-KJD-009); holding 2.28.0 or 2.27.1
keeps that warning.

## D10. Installed against pinned (L4-PRV-046)

Decision:
- `ProbeCtx.pins: Mapping[str, str]` (empty: the catalog's), set by the Factory from `effective_pins(cfg)`, like
  `min_remaining_percent`. `_binary` adds `pin` and `pin_source` to a passing step's detail for every adapter with a
  pin, and `major` for every gated adapter (Kiro now too). `probe_identity` adds the profile's adapter's effective pin,
  so a changed override is never answered from the cache.
- `_step_text`: `binary 2.33.0 (pinned 2.32.0)` when the version differs from the pin, unchanged when it is equal.
  `l4 probe --json` carries the detail as it carries every step's.
- `to_event` (`availability.selected`): `probes.<profile>.binary_pinned` = the pin, only when it differs from
  `binary`.
- Doctor `ENV-015` (warn, scope as ENV-004, `INSTALL_FIX` attached so `--ci --fix` acts on it): for each adapter in
  `adapters_in_use`, the binary on the harness path and its `--version`. A missing binary or a wrong major is ENV-004's
  finding and is skipped here. Pass: `claude 2.1.288, kiro-cli 2.32.0 at their pins`, plus each override (`kiro-cli
  2.28.0 held by ci.cli_versions; L4 pins 2.32.0`). Fail (warn): `kiro-cli 2.33.0 at ~/.local/bin/kiro-cli, pinned
  2.32.0` per CLI; the fix line is `in CI l4 doctor --ci --fix installs the pins; on this machine: <manual_command>`.
  It costs one `--version` per CLI in use, so `doctor --ci` stays within L4-NFR-001's 30 s [I].

Why both doctor and the probe: doctor runs once per job before provisioning acts; the probe runs before each
selection and is what a run's ledger keeps.

## D11. How a pin moves

`scripts/kiro_pin.py VERSION` (maintenance, not shipped, network on demand) reads `stable/index.json`, prints the
`KIRO_SHA256` row and the `prereqs.sh` lines for that version, and exits 1 when the version or one of the four Linux zips
is missing. Moving the Kiro pin then means: run it, paste, recompute one digest over the downloaded bytes, record the
fixtures under `tests/fixtures/recorded/kiro-cli/<version>/` (L4-FAC-007), run the live Kiro-judge test, and write a
CHANGELOG line. A pin never moves to a new major in the same release that records it.

## D12. Docs, SPEC, CHANGELOG

- SPEC: L4-PRV-042..046 after L4-DOC-002's rules (before the doctor table) and L4-OCG-005 after L4-OCG-004; scenarios
  SCN-PRV-113..128 after SCN-PRV-112 and SCN-OCG-11..14 after SCN-OCG-10; `ci.cli_versions` in §3.2; ENV-015 in the
  doctor table; the kiro row of §8.3 (the major and the implementer's `settings/cli.json`); L4-DOC-002's "the Kiro
  installer" sentence; change-table row 57.
- Runbook: 7.4 gets the Kiro 3 entry beside the OpenCode v2 one; a new 10.7 "Agent CLI versions" (the pins, ENV-015,
  what CI does, what a person does, `ci.cli_versions`, macOS Kiro).
- `docs/runner/README.md`: the PRQ-12 row (pinned, archive, digest) and a PRQ-21 row.
- Skill: `adopt.md` (a GitHub-hosted runner installs every CLI at the pin; holding one; move the harness pin before
  the key); `operate.md`'s error table: the Kiro major sentence, ENV-015's warning, the three load errors.
- CHANGELOG `## 0.4.20 (unreleased)`, above `## 0.4.19`. `tests/unit/docs/test_yolo_guardrails_docs.py:25` asserts that
  heading is absent: the change replaces that line with `assert changelog.index("## 0.4.20 (unreleased)") <
  changelog.index("## 0.4.19 (")` (task 7.1 says so).

## Contracts (the tasks share these; do not change one without the orchestrator)

```python
# src/l4/provision/catalog.py
KIRO_VERSION = "2.32.0"
KIRO_DOWNLOAD = "https://prod.download.cli.kiro.dev/stable"
KIRO_SHA256: dict[str, dict[str, str]]          # D1 table; keys linux-x64, linux-arm64, linux-x64-musl, linux-arm64-musl
KIRO_DMG_SHA256: dict[str, str]                 # D4, shown only
KIRO_MEMBERS = ("kirocli/bin/kiro-cli-term", "kirocli/bin/kiro-cli-chat", "kirocli/bin/kiro-cli")
KIRO_MEMBER_MAX = 512 * 1024 * 1024
ADAPTER_PINS = {..., "kiro-cli": KIRO_VERSION}
SUPPORTED_MAJORS = {"opencode": 1, "kiro-cli": 2}           # derived from the pins
MAJOR_WORDS = {"opencode": ("OpenCode v{m}", "opencode-ai {s}.x", "opencode-ai@{pin}", "OpenCode 2"),
               "kiro-cli": ("Kiro CLI {m}", "kiro-cli {s}.x", "kiro-cli {pin}", "Kiro CLI 3")}
def kiro_platform(platform: str, libc: str | None = ...) -> str: ...          # D3; ValueError off Linux
def kiro_archive_url(version: str, kiro_key: str) -> str: ...
def effective_pins(cfg: L4Config | None) -> dict[str, tuple[str, str]]: ... # adapter -> (version, "catalog"|"ci.cli_versions")
def major_problem(adapter: str, binary: str, version_text: str, pin: str) -> str | None: ...  # wording from MAJOR_WORDS
def catalog_hash(adapters: Iterable[str] = (), overrides: Mapping[str, str] | None = None) -> str: ...

# src/l4/provision/runner.py
def is_satisfied(tool: ToolSpec, found: str | None, *, exact: bool = False) -> bool: ...
def plan_fixes(..., replace_present: bool = False) -> list[FixAction]: ...
# src/l4/provision/install.py
def install_planned(..., replace_present: bool = False) -> list[FixAction]: ...

# src/l4/doctor/context.py
DoctorContext.ci: bool = False
# src/l4/agents/base.py
ProbeCtx.pins: Mapping[str, str] = {}
# src/l4/config/schema.py
CiCfg.cli_versions: dict[str, str] = {}
```

Texts: D5's reason `found <found>, pinned <pin>`; D8's sentence; D9's three load errors and its `manual` text; D10's
probe and ENV-015 lines; D4's macOS line. Ledger: `availability.selected.probes.<profile>.binary_pinned`.

## Collisions

- `opencode-v2` (row 52, also 0.4.20, in review) edits `SUPPORTED_MAJORS` and `major_problem` (a per-profile
  `cli_major`), `catalog_pins` (`agent:opencode2`, `npm:opencode2`), `required_tools`, `clis_cache_hash`, ENV-004,
  LIVE-005, `_verified`, `prereqs.sh` (PRQ-20, `OPENCODE2_VERSION`) and the regex of
  `test_catalog_pins_equal_the_defaults_in_prereqs_sh`. Merge order: `opencode-v2` first, this change rebased on it.
  Then `MAJOR_WORDS` gains opencode2's wording from that change, `ci.cli_versions` accepts `opencode2` as a key (its
  catalog name), the exact pin applies to `opencode2` like every agent, and PRQ-21 stays 21. If this change lands
  first, `opencode-v2` takes the same three steps.
- `kiro-judge` (shipped in 0.4.19): `JUDGE_SETTINGS` is unchanged; only `write_harness_agent` writes a settings file.

## Risks

- **A shared persistent runner flips versions.** Two repositories on one runner user that pin different harness
  releases (or different overrides) replace each other's CLI at every `doctor --ci --fix`. Each job still runs its own
  pin, which is the intent; the cost is a download per job, and a job running at the same time as another's replace
  could see a binary change under it. The runner rule is already one job at a time (PRQ-16's `concurrent=1`).
  Open question 1.
- **A repository's `.kiro/settings/cli.json`** overrides the global value for an implementer whose working directory is
  the worktree [D], so a repository could turn Kiro's self-update back on for its implementer steps. D10's check at the
  next job catches the drift.
- **The digests are the vendor's published values.** Task 1.1 recomputes the pin's four over the bytes before they ship.
- **`check_for_update_on_startup` on Codex 0.160.0** is [U]; task 3.1 checks it before the argv changes.
- **Every consumer's agent-CLI cache misses once** after the upgrade (the catalog gains the Kiro pin).

## Out of scope / follow-ups

- Kiro CLI 3 (a change of its own: record, then move the pin and the gate together).
- Harness-held digests for Claude Code (its signed `manifest.json` per version [D]) and for the npm CLIs.
- A private `KIRO_HOME` for read-only and `options.agent` steps (K5).

## Open questions (each with the recommended answer)

1. **Should each CLI run from a per-version directory, so repositories on different pins can share a runner user?**
   Recommended: not in 0.4.20. Keep one installed version per user; revisit only if a shared runner reports flips.
2. **Should a Kiro override outside `KIRO_SHA256` be installable with a digest given in the config?** Recommended: no.
   The harness installs only what it holds digests for; a team that needs another version installs it and declares
   it.
3. **Should the Codex app-server probe also get `-c check_for_update_on_startup=false`?** Recommended: no, unless task
   3.1 finds that `app-server` checks for updates.
4. **Should Claude Code and Codex get major gates?** Recommended: not in this change (L4-OCG-001's note).
