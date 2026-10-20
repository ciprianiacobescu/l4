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
  min_version`"; `plan_fixes` marks a satisfied tool `already present`, a floor above the pin `skipped`, an install
  that `ci.self_provision` forbids `skipped`, else `planned` (reason `found <found>, need <min_version or pin>`). So
  today a local `l4 doctor --fix` leaves a present CLI that meets the floor alone, and installs the pin over one below
  the floor: Claude's installer with the pin, `npm install --save-exact` of the pin, and for Kiro the saved installer,
  which over an existing `~/.local/bin/kiro-cli` reads a y/N answer from `/dev/tty` (it fails without a terminal, as in
  CI; in a terminal it waits on a prompt the harness captured [I]).
- `src/l4/provision/install.py`: `_install_agent` runs the saved Kiro installer with `bash` and no argument; Claude's
  installer gets the pin as its argument; Codex and OpenCode are `npm install --save-exact <pkg>@<pin>` into
  `$L4_HOME/npm`, linked into `~/.local/bin`. `_verified(ctx, tool)` checks the floor (`is_satisfied`), not the pin.
  `_verified`, `plan_fixes` and doctor's `_cli_problem` ("its OpenCode major cannot be checked") word a wrong major as
  OpenCode. There is no provisioning lock: `provision_lock` (runner-provisioning 2.2) is named in two module docstrings
  and was never built.
- `src/l4/doctor/registry.py` `exit_code`: only a failing check of severity `error` makes doctor exit 3; a warning
  never does. `src/l4/doctor/fix.py` applies the fix of a failing check, warnings included.
- `src/l4/ci/github.py`: the GitHub template without the action (`l4.github.yml`, hosted) keeps one tool cache keyed by
  the harness commit or by `hashFiles` of the vendored `catalog.py` and `l4-setup.sh` (`cache_key`), not by
  `l4 ci cache-key clis`.
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
  → 200, 348,674,736 bytes. Per-version `manifest.json` paths answer 403. A version the CDN does not serve answers 403,
  not 404 (`stable/9.9.9/kirocli-x86_64-linux.zip` → 403). The review re-ran the HEADs of all four 2.32.0 Linux zips,
  of 2.28.0 `x86_64` gnu and `aarch64` musl and of 2.27.1 `x86_64` musl and `aarch64` gnu: 200 with the index's sizes.
- `https://prod.download.cli.kiro.dev/stable/index.json` (1.4 MB) lists 176 versions, newest first, each package with
  `download` (`<version>/<file>`), `sha256` and `size`. Its 24 packages of 2.32.0 equal `stable/latest/manifest.json`'s.
- The archive (2.32.0 x86_64 gnu, read through HTTP range requests of its central directory and of three small
  members; 76 kB fetched): `kirocli/README`, `kirocli/BUILD-INFO` (`BUILD_VERSION=2.32.0`,
  `BUILD_TARGET_TRIPLE=x86_64-unknown-linux-gnu`), `kirocli/install.sh`, and `kirocli/bin/` with `kiro-cli`
  (43,931,168 bytes), `kiro-cli-chat` (207,496,744), `kiro-cli-term` (34,060,512), and two 2-line shell wrappers `q` and
  `qchat` that call `"$HOME/.local/bin/kiro-cli"`. The archive's `install.sh`, user mode: checks the target triple and
  glibc, then `install -m 755` of `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` into `$HOME/.local/bin/`, then
  `kiro-cli setup` unless `KIRO_CLI_SKIP_SETUP` is set (the outer installer sets it). No prompt; it overwrites.
  The central directories of the other three 2.32.0 Linux archives, and of the 2.28.0 and 2.27.1 `x86_64` gnu and
  `aarch64` musl archives, list the same `kirocli/bin/` members, all regular files of mode 0755; the largest is
  `kiro-cli-chat` of 2.28.0 x86_64 at 214,425,448 bytes.
- Kiro's settings page: `app.disableAutoupdates` "Disable background auto-updates"; settings live in
  `~/.kiro/settings/cli.json`, a workspace `.kiro/settings/cli.json` overrides the global value, and "In V3, [`KIRO_HOME`]
  overrides the global Kiro directory for configuration, sign-ins, sessions, and agent state" [D]. No environment
  variable turns updates off [D: none listed].
- Kiro 2.32.0 has no public release notes. Its `chat --help` names `--agent-engine … "v2" (default)` and `--v2 Use the
  V2 agent engine (the pre-3.0 default)` [V, kiro-judge R13 and 2026-10-20].

### Self-update switches [D unless marked; each page re-read by the review on 2026-10-20]

| CLI | Switch | Source |
|---|---|---|
| Claude Code | `DISABLE_AUTOUPDATER`: "Set to `1` to disable automatic background updates. Manual `claude update` still works. Use `DISABLE_UPDATES` to block both". `DISABLE_UPDATES`: "Set to `1` to block all updates including manual `claude update` and `claude install`. Stricter than `DISABLE_AUTOUPDATER`. Use when distributing Claude Code through your own channels and users should not self-update". The `env` key of `settings.json`: "Claude Code reads them directly from the file, so they take effect no matter how `claude` was launched". Whether 2.1.288 already knows `DISABLE_UPDATES` is [U]; an unknown variable is ignored [I]. | code.claude.com/docs/en/env-vars |
| Codex | config key `check_for_update_on_startup` (`boolean`): "Check for Codex updates on startup (set to false only when updates are centrally managed)". No environment variable found. Whether 0.160.0 knows the key, and whether `codex exec` or `codex app-server` checks at all, is [U] (task 3.1). An npm install in the harness prefix is not replaced by Codex itself [I]. | the Codex configuration reference (developers.openai.com/codex/config-reference redirects to learn.chatgpt.com/docs/config-file/config-reference) |
| OpenCode | `OPENCODE_DISABLE_AUTOUPDATE=1` and `"autoupdate": false` | [V code], already set |
| Kiro CLI | setting `app.disableAutoupdates` (boolean) "Disable background auto-updates", example `kiro-cli settings app.disableAutoupdates true`; "Settings are stored in `~/.kiro/settings/cli.json`", a workspace `.kiro/settings/cli.json` overrides the global value; no environment variable controls updates. Read from `KIRO_HOME` as `(global)` [V, live run 1]; that the CLI acts on it [I]. Whether a Linux zip install updates itself in the background at all [U]. | kiro.dev/docs/reference/settings/ (the old /docs/cli/reference/settings/ redirects there) |

## Goals / Non-goals

Goals: every agent CLI that L4 installs is installed at its pin, Kiro included, and a Kiro download is trusted only
through digests that ship with the harness. In CI a CLI of another version is replaced. On a person's machine
`l4 doctor --fix` keeps today's floor rule: a CLI that meets the profile's `min_version` is reported, never replaced,
and one below it is installed at the pin as today (the person asked for `--fix`); a Kiro CLI 3 there is left alone
with the fix named. No process that L4 starts updates a CLI. A kiro-cli 3 is refused by name. A team can hold another
version of the same major by configuration. Doctor and the probe say which version runs and which is pinned.

Non-goals (D13 gives the why of the first four):
- Kiro CLI 3 support (a later change, after its streams are recorded; L4-FAC-007 already says the 2.32.0 shapes are
  re-recorded before the pin moves to 3.x).
- Digests in the harness for Claude Code, Codex or OpenCode. Their trust anchors stay as today: Claude's installer and
  npm's registry integrity.
- Major gates for Claude Code or Codex.
- A per-version install directory that lets two harness releases share one runner user without replacing each other's
  CLIs.
- A team-supplied sha256 for a Kiro version outside `KIRO_SHA256`.
- An automatic install of Kiro on macOS (D4).
- A Kiro row in the skill's `yolo_preflight.py`: it checks the OpenCode major of a local judge only, with its own copy
  of the OpenCode pin, and reads no `ci.cli_versions`; a local Kiro CLI 3 judge is refused by the probe's `binary` step.

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
row equals `stable/latest/manifest.json`) [V as published: the review compared all twelve Linux digests and the three
disk-image digests below with `index.json` (176 versions) and the 24 packages of 2.32.0 with `stable/latest/manifest.json`
on 2026-10-20; recomputed over the bytes by task 1.1]:

| version | `linux-x64` | `linux-arm64` | `linux-x64-musl` | `linux-arm64-musl` |
|---|---|---|---|---|
| 2.32.0 | `7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb` | `f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848` | `f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485` | `219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b` |
| 2.28.0 | `4d6d20c3ffed99904081a062678b3c1978dc7d68c9f6c530f3f28f163011c8ee` | `39169fc43557ff3c007ccf5388ff95413539b2c6a8dfab6c69e4a7b8899bebbc` | `8ee7e1b789af4d506ebd661fe4a2d88a1cf20b4027170aae7c3cd1daf348b98c` | `c91fb5b7bec67acbbe0cdbc239f7a6b8e541f6bff2db32e418b0e3090f5e38b2` |
| 2.27.1 | `e68927fe0bffb752746a573010cb68792b0f3e97be3a6ce73792c9cc02f08007` | `abdb1f8167693f34163c1b053ccdce4819e191140e9319a0c78c55c252b11d83` | `7c7a9f5e3284c82cc6f0fb1a301597368538adb83d916927e664c957a9f953ef` | `937ff1ae3df373717b66cc09aec79c3b7f0b8e53968d746e3a4545722e1e4587` |

`KIRO_DMG_SHA256` (shown, never used by an install, D4): 2.32.0 `88721f97dbe98c9e4f84a46e8a2584a8dd29289b81264d96ee2987dd2c014e3c`,
2.28.0 `5119dfebf8234d336af874af631d1039e3b9a9bbd6da1c71874f5855173a91c8`, 2.27.1
`850da13e0667f5bc4ef645526b5ba08a50dc8442cd92bad1ffc7546a7ce8195c`.

The harness never reads `latest/` and never fetches `manifest.json` or `index.json` to install. `index.json` is read only
by `scripts/dev/kiro_pin.py` (D11), a maintenance script that prints the table rows for a version, and by no test that
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
   with both digests, ending `do not install it by hand: report it, or hold another version in ci.cli_versions (one the
   harness holds)` (no manual command: it would install the archive that failed), and nothing under `~/.local/bin` has
   changed.
4. Open it with `zipfile.ZipFile` and check before writing anything: each of the members `kirocli/bin/kiro-cli-term`,
   `kirocli/bin/kiro-cli-chat` and `kirocli/bin/kiro-cli` (by those exact names, `KIRO_MEMBERS`) must exist, be a
   regular file (the Unix mode in `external_attr >> 16` is `S_IFREG`, not a link) and be at most 512 MiB
   uncompressed (`file_size`); otherwise the action fails naming the member and nothing is written.
5. Stage: each member, in `KIRO_MEMBERS` order, is streamed to `~/.local/bin/.<name>.tmp.<pid>` (same directory, so the
   rename is atomic per file) and given mode 0o755. Any error while staging (a short read, a full disk, a CRC error,
   an `OSError`) removes every staged file and fails the action; `~/.local/bin` then holds what it held before.
6. Swap: only when all three are staged, each existing target is first kept beside it as `<name>.bak.<pid>` (a hard
   link, else a copy), then each staged file is moved onto `~/.local/bin/<name>` with `os.replace`, `kiro-cli` last.
   The swap is all-or-nothing: when a rename fails, every target is restored from its backup, a file that had no
   original is removed, every backup is removed and the action fails; on success the backups are removed. (A crash
   between the renames can still leave a mixed set, which step 7, ENV-015 and the next `doctor --ci --fix` report and
   repair.) Staging opens each file with `O_CREAT|O_EXCL|O_NOFOLLOW` after unlinking the path, so a link planted at
   the predictable name is never followed. The archive's `install.sh`, `q`, `qchat`, `README` and `BUILD-INFO` are
   not extracted and no file of the archive is run.
7. `_verified` reads `kiro-cli --version` from the harness path; it must be the target version (D5), else the action
   fails naming the path and both versions.

Failure modes, each a `failed` action with the manual command (a refused download has its own text, below) and exit 3 (`_apply` maps them today): the CDN answers 403
for a version it does not serve [V] (`HttpxFetcher` raises `OfflineError` for any status ≥ 400; the Kiro install turns
403 and 404 into `cannot download kiro-cli <v> from prod.download.cli.kiro.dev (HTTP 403): that version may no longer
be served; hold another version in ci.cli_versions (one the harness holds) or report it`, with no manual command: the
same URL fails again); a 5xx is retried once; a transport error; a digest
mismatch (`IntegrityError`, both digests, no manual command; the text says "the harness's digest" for Kiro, whose digests are the
harness's own table, and "the published" for Node, whose digest comes from `SHASUMS256.txt`); a missing, linked or oversized member; a staging error (`OSError`,
`zipfile.BadZipFile`, which `_apply` gains). Disk: the archive (at most 166 MB for the three versions held) and the
staged files (at most 290 MB) coexist for the length of the step.

`manual_command` for Kiro on Linux calls `kiro_platform(platform)` (D3) and names the versioned URL, its digest, the
check (`echo "<digest>  <file>" | sha256sum -c`), `unzip` and the three `install -m 755` lines; `kiro_platform` raising
`ValueError` (macOS) gives the disk-image line of D4.

Why the vendor's layout (three regular files in `~/.local/bin`) and not a versioned directory with links: the
archive's own `install.sh` puts exactly these three files there [V], the `q` and `qchat` wrappers call
`$HOME/.local/bin/kiro-cli` [V], and how `kiro-cli` finds `kiro-cli-chat` through a symlink is [U]. The agent-CLI
cache already saves `~/.local/bin` [V], so nothing in the action changes. Why not run the archive's `install.sh`: it is
code from a download, and without `KIRO_CLI_SKIP_SETUP` it runs `kiro-cli setup` (shell integrations, dotfiles) [V];
its only other effect is the three copies, which the harness does itself.

`zipfile` has no `filter="data"`; the member allow-list by exact name is the whole defence, and no member name from the
archive becomes a path. (The index also lists a `kirocli-<arch>-linux.tar.xz` per version, which `tarfile`'s `data`
filter could read; the zip stays because it is the file the vendor's installer uses and the one recorded here.)

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

Decision: on `darwin-*` a Kiro action that would install (in any mode) is `manual` and nothing is downloaded; a
present `kiro-cli` that satisfies the pin or the floor stays `already present`. `manual_command` names:
`download https://prod.download.cli.kiro.dev/stable/2.32.0/Kiro%20CLI.dmg, check it with shasum -a 256 (88721f97…
full digest), open it and copy Kiro CLI.app to /Applications (this replaces an installed Kiro CLI)`. Doctor's ENV-004
and ENV-015 lines carry the same text.

Why: the macOS install mounts a disk image, copies an app bundle into `/Applications`, asks on `/dev/tty` before
replacing one and starts the app [V: the installer]. That is a person's decision on a person's machine, and L4 runs
agent steps on Linux only (bubblewrap), so a Mac never needs the pin for `l4 run`.

## D5. Exact in CI; today's floor rule on a person's machine (L4-PRV-043)

Decision:
- `ToolSpec.version` of an agent is its effective pin (D9). `is_satisfied(tool, found, *, exact: bool = False)`: an
  agent of a wrong major is never satisfied (as today); with `exact`, an agent is satisfied only when
  `parse_version(found) == parse_version(tool.version)`; without, today's floor rule holds unchanged.
- `plan_fixes` and `install_planned` gain `replace_present: bool = False`, passed to `is_satisfied` as `exact`, and
  `install_planned` stores it in `_Ctx.replace_present`. `DoctorContext` gains `ci: bool = False`, set from
  `l4 doctor --ci`; `fix_provision` and `survey_provision` pass `replace_present=ctx.ci`. Every generated CI file runs
  `l4 doctor --ci --fix` or `l4 doctor --ci` [V templates], so "CI" is exactly `--ci`.
- The order of `plan_fixes` stays: satisfied → `already present`; floor above the pin → `skipped`; `ci.self_provision`
  false → `skipped` (an exact pin never overrides it); otherwise `planned`, or `manual` for the Kiro cases below.
- Under `--ci --fix`, a present agent CLI of another version is `planned` with the reason `found <found>, pinned <pin>`
  (`<pin> (ci.cli_versions)` for an override) and installed as for a missing one: Claude's installer with the pin,
  `npm install --save-exact <pkg>@<pin>` into the harness prefix, the Kiro archive (D2). L4-OCG-004's guard stays as it
  is: a regular file at `~/.local/bin/opencode` is never replaced. The Kiro files at `~/.local/bin` are replaced
  whatever they are: they are the vendor's layout, and in CI they belong to the runner.
- `_verified(ctx, tool)` passes `exact=ctx.replace_present` to `is_satisfied` for an agent, and a Kiro install is
  always checked exactly (D2 step 7). An exact miss fails the action with `installed <found>, but <pin> (pinned) is
  needed` (the floor miss keeps `installed <found>, but >= <min_version> is needed`). So an installer that does not
  downgrade (Claude's native installer over a newer native install is [U]) is a named `failed` action and exit 3,
  never an `applied` action at the wrong version.
- Without `--ci` (decision of the owner's delegate, 2026-10-20), `l4 doctor --fix` keeps today's floor rule:
  - a present agent CLI of the supported major that meets the profile's `min_version` (or whose profiles set none) is
    `already present` and never replaced; ENV-015 (D10) warns with both versions and the command;
  - one below `min_version` is `planned` with today's reason `found <found>, need <min_version>` and installed at the
    pin user-locally, as today: the person asked for `--fix`, and the action line says what it does. For Claude,
    Codex and OpenCode this is unchanged. For Kiro the effect changes: the saved installer used to stop on its `/dev/tty`
    prompt over an existing `kiro-cli` (Context), and the archive now replaces the three files without a prompt;
  - a present `kiro-cli` of another major is `manual` with the D8 reason and the command, never `planned`: its files
    stay as they are (a person may run Kiro CLI 3 for their own work) and the message names the fix;
  - on macOS a Kiro action that would install (missing, below its floor, another major) is `manual` (D4);
  - a present `opencode` of another major keeps L4-OCG-004's local behaviour (the pinned v1 in the harness prefix
    behind a guarded link), because that rule was decided and shipped on its own evidence;
  - a missing CLI is installed at the pin, as today.
- `_floor_above_pin` and the profile's `min_version` keep their meaning as a floor that ENV-004 checks.

Why `--ci` and not `ci.self_provision`: `self_provision` resolves true on a person's machine too (`auto` is true on
local runs [V L4-DOC-002]), so it cannot tell a runner from a laptop; `--ci` is what every CI file passes and what a
person does not. Why a local CLI that meets the floor is not replaced: it may be the person's own install, used outside
L4; ENV-015 tells them, and the probe and the ledger record which version ran.

## D6. prereqs.sh PRQ-12 (L4-PRV-043, L4-OCG-005)

Decision: the top block gets `KIRO_VERSION=${KIRO_VERSION:-2.32.0}` (the comment "floor, not an exact pin" goes) and
four digests, the pin's row of D1: `KIRO_SHA256_X86_64`, `KIRO_SHA256_AARCH64`, `KIRO_SHA256_X86_64_MUSL`,
`KIRO_SHA256_AARCH64_MUSL`, each `${NAME:-<digest>}`. `check_kiro` passes only when the runner user's `kiro-cli
--version` equals `KIRO_VERSION`; its DETAIL names the found version, the path and `pinned $KIRO_VERSION`, and a major
other than 2 adds `Kiro CLI <major>; L4 runs Kiro CLI 2`. `apply_kiro` never runs `kiro-cli update` and never the
installer script: as the runner user it picks `x86_64` or `aarch64` from `uname -m` and gnu or musl by `ldd --version`
with D3's thresholds, downloads `https://prod.download.cli.kiro.dev/stable/$KIRO_VERSION/kirocli-<arch>-linux[-musl].zip`
into a `mktemp -d` under the runner user's home, checks it with `sha256sum -c` against the matching digest, unzips it,
and runs `install -m 755` for `kiro-cli-term`, `kiro-cli-chat` and `kiro-cli` into `~/.local/bin` (`unzip`, `curl`
and `sha256sum` come from PRQ-02's packages). The download uses `curl -fsSL`, so a 403 for a version the CDN does not
serve fails the step; the temporary directory is removed however the step ends, and no `install` runs before the
check passed. A `KIRO_VERSION` set without its digests fails at `sha256sum -c` with a DETAIL that says to set the four
`KIRO_SHA256_*`. A drift test compares `KIRO_VERSION` and the four digests with the catalog. The `--without-kiro`
switch stays.

Why `install -m 755` in the script and not the archive's `install.sh`: the same reason as D2; the three lines are what
that script does [V].

## D7. Self-update off (L4-PRV-044)

Decision: each CLI gets the switch it offers, where the harness starts it (runs, judges, clarifiers, readiness reviews,
probe steps, and for Claude also every `--version` read and installer); the mechanism differs, so the reach differs
(below):
- Claude Code: `ClaudeCodeAdapter.extra_env` gains `DISABLE_AUTOUPDATER=1` and `DISABLE_UPDATES=1`, and so does the
  environment of every probe step of a `claude` binary, the `binary` step included (`probe_claude`'s extra, and
  `_binary` for the `claude` binary). Both, because `DISABLE_UPDATES` is the documented switch for "your own channels"
  [D] and whether 2.1.288 knows it is [U], while `DISABLE_AUTOUPDATER` is the older one [D]. An installer gets
  `DISABLE_AUTOUPDATER=1` only: `scrub_env` adds it to its allow-listed environment, which every installer and every
  provisioning `--version` read uses, and never `DISABLE_UPDATES`, which would block `claude install` [D], the step
  Claude's native installer runs [I]. Doctor's own `--version` reads of `claude` (ENV-004, ENV-015, LIVE-005) pass
  `DISABLE_AUTOUPDATER=1` too. So no `claude` the harness starts runs with the background updater on, and PRQ-21 plus
  PRQ-09 give the runner the same pair of facts (updater off, `claude install` allowed).
- Codex: every `codex exec` argv (implementer, judge, hello) gains `-c check_for_update_on_startup=false` after
  `-c project_doc_max_bytes=0`. The key is documented [D]; whether 0.160.0 accepts it is [U], so task 3.1 checks first
  that the pinned binary does not refuse it (an isolated `HOME` and `CODEX_HOME`, no credential: a refused key is a
  configuration error before any login check). A refusal stops the task and goes to the orchestrator; the switch is not
  dropped silently. `codex app-server` (the auth and quota probe) gets nothing (D13): task 3.1 also starts it in the
  same isolated `HOME` and records its standard error; only if that shows an update check does the switch go on its
  argv too, as a change the orchestrator approves.
- OpenCode: unchanged (`OPENCODE_DISABLE_AUTOUPDATE=1`, `"autoupdate": false`) [V].
- Kiro: `write_harness_agent` also writes `settings/cli.json` = `{"app.disableAutoupdates": true}`, only that key (the
  judge's other keys would change what an implementer inherits). The judge, the hello and the listing keep
  `JUDGE_SETTINGS`. The `whoami` and `/usage` probe steps, a read-only step and an implementer with `options.agent`
  run without a private `KIRO_HOME` (today's K5 gap) [V code], so they read the runner user's settings: PRQ-21 sets the
  key there on a self-hosted runner, and on a disposable runner D10's exact check at the start of the next job is the
  guard.
- The runner image: `prereqs.sh` PRQ-21 "agent CLI self-update off" (PRQ-20 is reserved for `opencode-v2`, which
  ships later; the runner README notes the gap). Check: the runner user's `~/.claude/settings.json` has
  `.env.DISABLE_AUTOUPDATER == "1"`, and, when Kiro is installed (`WITH_KIRO` and `kiro-cli` on the runner user's
  PATH), `~/.kiro/settings/cli.json` has `."app.disableAutoupdates" == true`, both read with `jq` (PRQ-02 installs it).
  Apply, as the runner user: merge `{"env": {"DISABLE_AUTOUPDATER": "1"}}` into the Claude file and
  `{"app.disableAutoupdates": true}` into the Kiro file with `jq` (every other key kept; a missing file and its
  directory are created; a file that is not JSON is left untouched and the step is FAILED naming it; the merge writes a
  temporary file beside the target and renames it). The Kiro file is the global settings file the vendor documents [D],
  in the flat dotted-key form the judge's `settings/cli.json` uses and `settings list` read as `(global)` [V, live run
  1], so no `kiro-cli` runs and no login state matters. Only `DISABLE_AUTOUPDATER`, never `DISABLE_UPDATES`, in the
  image: PRQ-09 runs Claude's installer as the same user. OpenCode needs nothing there (every run gets an empty
  `XDG_CONFIG_HOME` and the switches) and Codex has no self-update of the harness prefix [I].

Why: a probe runs `claude` with the real `HOME` [V], and a native Claude install updates itself in the background
[D], so on a persistent runner the harness's own probe could move the version it then runs. A human's interactive
login on the runner (PRQ-15's instructions) starts the same CLIs, hence PRQ-21. On a GitHub-hosted runner the
agent-CLI cache is saved right after `doctor`, before any agent runs [V template order], so even a CLI that updated
itself later in the job cannot put another version into the cache under the pin's key.

## D8. The kiro-cli major gate (L4-OCG-005)

Decision: `SUPPORTED_MAJORS = {"opencode": 1, "kiro-cli": 2}`, each derived from its pin as today. Every text about a
wrong major comes from one per-adapter table `MAJOR_WORDS` (Contracts), so the OpenCode texts stay byte-identical and
Kiro's are:

- `major_problem`: `kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli 2.32.0 (in CI l4 doctor --ci
  --fix installs it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 release`,
  with the binary, the found version, its major and the effective pin filled in;
- the `plan_fixes` reason: `found 3.0.0 (Kiro CLI 3), need kiro-cli 2.x (pinned 2.32.0)`;
- the `_verified` text: `kiro-cli at <path> reports 3.0.0 (Kiro CLI 3) after the install, need kiro-cli 2.x (pinned
  2.32.0)`;
- ENV-004's fail-closed text (`_cli_problem`, a gated CLI whose `--version` holds no version): `kiro-cli reports no
  version, so its Kiro CLI major cannot be checked` (OpenCode keeps `… its OpenCode major cannot be checked`);
- the load error of D9: `… is Kiro CLI 3; this harness runs Kiro CLI 2 …` (OpenCode: `… is OpenCode 2; this harness
  runs OpenCode 1 …`).

Every caller of L4-OCG-001/002 applies it: the probe `binary` step (fails, no `auth`, `quota` or `hello`), ENV-004
(whether or not `min_version` is set), LIVE-005 (error, before the recorded-version comparison), `doctor --fix` (D5) and
PRQ-12 (D6). Each caller passes the effective pin (D9), not `ADAPTER_PINS[adapter]`.

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

Validation at load (a `ValueError` the loader turns into exit 2), each message naming the key. `catalog.py` imports
`L4Config` from `l4.config.schema`, so the validator imports `ADAPTER_PINS`, `SUPPORTED_MAJORS` and `MAJOR_WORDS` from
`l4.provision.catalog` inside its function body, never at the top of `schema.py` (a top-level import is a cycle; a
test imports `l4.config.schema` alone in a fresh interpreter):
- a key that is not an adapter of `ADAPTER_PINS` (`claude-code`, `codex`, `kiro-cli`, `opencode`): `ci.cli_versions:
  unknown agent CLI <key> (one of claude-code, codex, kiro-cli, opencode)`;
- a value that is not `N.N.N`: `ci.cli_versions: <key>: is not a version N.N.N` (the value is never echoed: it may be a
  token; the key of an unknown-adapter error goes through the loader's redactor, and pydantic's own input echo is off);
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
declare it and is not replaced. A `manual` action is not `failed`, so the consequence is the checks': with another
`kiro-cli` present, ENV-015 warns and doctor exits 0, so the job runs the version that is there and the probe and the
ledger record it (L4-PRV-046); with none, ENV-004 fails as for any missing CLI. Claude Code, Codex and OpenCode accept
any version of the supported major (their installers keep today's anchors). An override that equals the catalog pin
is noted by ENV-015 (`… remove it`).

An override below a profile's `min_version` (for example `{kiro-cli: "2.28.0"}` beside a Kiro judge with `min_version:
"2.32.0"`, the adoption example) makes the effective pin a version the floor refuses: `_floor_above_pin` makes the
action `skipped` with today's text `min_version 2.32.0 is above the pinned 2.28.0; not installing`. A present
`kiro-cli` that meets the floor keeps running (ENV-015 warns that it is not the held 2.28.0); with none, or one below
the floor, ENV-004 fails for that profile. That is the existing floor rule, not a new check: lower the floor or drop
the override.

On the GitHub template without the action (`l4.github.yml`, Context), the tool cache key does not read the
configuration, so an override does not move it: `doctor --ci --fix` still installs the override in every job (the
pin is exact), at the cost of one download per job while the restored cache holds another version. The action's
agent-CLI cache (L4-ACT-002) moves with it. Runbook 10.7 says so and points to `harness.delivery: action`.

Why a config key and not an environment variable: the version a repository's agents run is a property of the
repository, it must reach `l4 ci cache-key clis` (which reads the config [V]), and a strict schema validates it. Why
one map: one binary per machine serves every profile of an adapter, so a per-profile version would be ambiguous.
Note for kiro-judge: CFG-011 already warns when a Kiro judge may run below 2.32.0 (L4-KJD-009); holding 2.28.0 or 2.27.1
keeps that warning.

## D10. Installed against pinned (L4-PRV-046)

Decision:
- `ProbeCtx.pins: Mapping[str, str]` (empty: the catalog's) and `ProbeCtx.pin_sources: Mapping[str, str]`, set by the
  Factory from `effective_pins(cfg)`, like `min_remaining_percent`. `_binary` adds `pin` and `pin_source` to a passing
  step's detail for every adapter with a pin, and `major` for every gated adapter (Kiro now too).
  `probe_identity(profile, cfg, environ, pin=None)` hashes `pin` with the other settings when it is given, and both
  callers in `fallback.py` pass `self._ctx.pins.get(profile.adapter)`, so a changed override is never answered from the
  cache.
- `_step_text`: `binary 2.33.0 (pinned 2.32.0)` when the version differs from the pin, unchanged when it is equal.
  `l4 probe --json` carries the detail as it carries every step's.
- `to_event` (`availability.selected`): `probes.<profile>.binary_pinned` = the pin, only when it differs from
  `binary`.
- Doctor `ENV-015` (warn, scope as ENV-004, `INSTALL_FIX` attached so `--ci --fix` acts on it): for each adapter in
  `adapters_in_use`, the binary on the harness path and its `--version`. A missing binary or a wrong major is ENV-004's
  finding and is skipped here. Pass: `claude 2.1.288, kiro-cli 2.32.0 at their pins`, plus each override (`kiro-cli
  2.28.0 held by ci.cli_versions; L4 pins 2.32.0`). Fail (warn): `kiro-cli 2.33.0 at ~/.local/bin/kiro-cli, pinned
  2.32.0` per CLI; the fix line is `in CI l4 doctor --ci --fix installs the pins; on this machine: <manual_command>`. ENV-015 runs before
  the fixes, so on a cold cache it passes with `no agent CLI to compare with its pin`; `apply_fixes` therefore runs it
  again after any `applied` install of an agent CLI and reports that result.
  It costs one `--version` per CLI in use, so `doctor --ci` stays within L4-NFR-001's 30 s [I].

Why both doctor and the probe: doctor runs once per job before provisioning acts; the probe runs before each
selection and is what a run's ledger keeps.

## D11. How a pin moves

`scripts/dev/kiro_pin.py VERSION` (maintenance, beside `release_commit.py`; the release commit ships no `scripts/`;
network on demand) reads `stable/index.json` (or `--index PATH`), prints the `KIRO_SHA256` row, the `KIRO_DMG_SHA256`
entry and the `prereqs.sh` lines for that version, and exits 1 when the version or one of the four Linux zips is
missing. Moving the Kiro pin then means: run it, paste, recompute one digest over the downloaded bytes, record the
fixtures under `tests/fixtures/recorded/kiro-cli/<version>/` (L4-FAC-007), run the live Kiro-judge test, and write a
CHANGELOG line. A pin never moves to a new major in the same release that records it.

## D12. Docs, SPEC, CHANGELOG

- SPEC: L4-PRV-042..046 after L4-DOC-002's rules (before the doctor table) and L4-OCG-005 after L4-OCG-004; scenarios
  SCN-PRV-113..128 after SCN-PRV-112 and SCN-OCG-11..14 after SCN-OCG-10; `ci.cli_versions` in §3.2; ENV-015 in the
  doctor table; the kiro row of §8.3 (the major and the implementer's `settings/cli.json`); L4-DOC-002's "the Kiro
  installer" sentence; L4-ACT-002's key sentence (the overrides of the CLIs in use); change-table row 57.
- Runbook: 7.4 gets the Kiro 3 entry beside the OpenCode v2 one; a new 10.7 "Agent CLI versions" (the pins, ENV-015,
  what CI does, what a person's `--fix` does and does not replace, `ci.cli_versions` and its cost on the template
  without the action, macOS Kiro).
- `docs/runner/README.md`: the PRQ-12 row (pinned, archive, digest), a PRQ-21 row, and a line that PRQ-20 is reserved
  for a later change.
- Skill: `adopt.md` (a GitHub-hosted runner installs every CLI at the pin; holding one; move the harness pin before
  the key; section 4d's "kiro-cli 2.32.0 or newer" becomes "kiro-cli 2.32.0, the harness's pin (a Kiro CLI 3 is
  refused)"); `operate.md`'s error table: the Kiro major sentence, ENV-015's warning, the three load errors.
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

class MajorWords(NamedTuple):   # every text about a wrong major (D8); fields: {binary} {version} {major} {supported} {pin}
    product: str                # "OpenCode" | "Kiro CLI"  (fail-closed text, load error)
    major_name: str             # "OpenCode v{major}" | "Kiro CLI {major}"
    need: str                   # "opencode-ai {supported}.x" | "kiro-cli {supported}.x"
    problem: str                # major_problem's sentence (OpenCode: today's L4-OCG-002 text, byte for byte)
MAJOR_WORDS: dict[str, MajorWords] = {
    "opencode": MajorWords("OpenCode", "OpenCode v{major}", "opencode-ai {supported}.x",
        "{binary} {version} is OpenCode v{major}; this profile runs v{supported} (opencode-ai {supported}.x): install "
        "opencode-ai@{pin} (l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release"),
    "kiro-cli": MajorWords("Kiro CLI", "Kiro CLI {major}", "kiro-cli {supported}.x",
        "{binary} {version} is Kiro CLI {major}; L4 runs Kiro CLI {supported}: install kiro-cli {pin} (in CI l4 doctor "
        "--ci --fix installs it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 "
        "release"),
}
# derived texts: plan_fixes "found {version} ({major_name}), need {need} (pinned {pin})"; _verified "{name} at {path}
# reports {version} ({major_name}) after the install, need {need} (pinned {pin})"; _cli_problem "{binary} reports no
# version, so its {product} major cannot be checked"; load "ci.cli_versions: {key}: {value} is {product} {major}; this
# harness runs {product} {supported} (L4-OCG-001, L4-OCG-005); a major moves with an L4 release, not with configuration"
def kiro_platform(platform: str, libc: str | None = ...) -> str: ...          # D3; ValueError off Linux
def kiro_archive_url(version: str, kiro_key: str) -> str: ...
def effective_pins(cfg: L4Config | None) -> dict[str, tuple[str, str]]: ... # adapter -> (version, "catalog"|"ci.cli_versions")
def major_problem(adapter: str, binary: str, version_text: str, pin: str) -> str | None: ...  # wording from MAJOR_WORDS
def catalog_hash(adapters: Iterable[str] = (), overrides: Mapping[str, str] | None = None) -> str: ...

# src/l4/provision/runner.py
def is_satisfied(tool: ToolSpec, found: str | None, *, exact: bool = False) -> bool: ...
def plan_fixes(..., replace_present: bool = False) -> list[FixAction]: ...
def scrub_env(env, paths) -> dict[str, str]: ...    # also DISABLE_AUTOUPDATER=1 (D7), never DISABLE_UPDATES
# src/l4/provision/install.py
def install_planned(..., replace_present: bool = False) -> list[FixAction]: ...
_Ctx.replace_present: bool = False                  # read by _verified (D5)

# src/l4/doctor/context.py
DoctorContext.ci: bool = False
# src/l4/agents/base.py
ProbeCtx.pins: Mapping[str, str] = {}
ProbeCtx.pin_sources: Mapping[str, str] = {}
# src/l4/availability/fallback.py
def probe_identity(profile: Profile, cfg: AvailabilityCfg, environ: Mapping[str, str], pin: str | None = None) -> str: ...
# src/l4/config/schema.py
CiCfg.cli_versions: dict[str, str] = {}            # validator imports the catalog inside its body (D9)
```

Texts: D5's reasons `found <found>, pinned <pin>` and `installed <found>, but <pin> (pinned) is needed`; D8's texts;
D9's three load errors and its `manual` text; D10's probe and ENV-015 lines; D4's macOS line. Ledger:
`availability.selected.probes.<profile>.binary_pinned`.

## Collisions

- `opencode-v2` (row 52, paused) ships after this change (decision of the owner's delegate, 2026-10-20: Kiro CLI 3.0's
  rollout by the end of October 2026 is the deadline). This change depends on nothing in it. When `opencode-v2`
  resumes, it rebases onto `pin-clis` and then extends this change's contracts to its `opencode2` catalog entry:
  `MAJOR_WORDS` gains opencode2's texts (its per-profile `cli_major` reads the table), `ci.cli_versions` accepts
  `opencode2` as a key (its catalog name, validated against its own major), the exact pin of D5 and ENV-015 apply to
  `opencode2` like every agent, `catalog_hash`'s overrides include it, and its PRQ-20 keeps its number (PRQ-21 is
  this change's). The files both touch, which its rebase resolves: `catalog.py` (`SUPPORTED_MAJORS`, `major_problem`,
  `catalog_pins`, `required_tools`, `clis_cache_hash`), ENV-004, LIVE-005, `_verified`, `prereqs.sh` and the regex of
  `test_catalog_pins_equal_the_defaults_in_prereqs_sh`.
- `kiro-judge` (shipped in 0.4.19): `JUDGE_SETTINGS` is unchanged; only `write_harness_agent` writes a settings file.

## Risks

- **A shared persistent runner flips versions.** Two repositories on one runner user that pin different harness
  releases (or different overrides) replace each other's CLI at every `doctor --ci --fix`. Each job still runs its own
  pin, which is the intent; the cost is a download per job. There is no provisioning lock (Context): two doctors at
  once on one runner user could interleave their renames (D2 step 6), and a job could see a binary change under it.
  Within one repository the generated jobs already run one at a time (`concurrency: group: l4` in both GitHub templates,
  `resource_group: l4` on GitLab); across repositories on one runner user only the runner's own limit does (GitLab
  `concurrent = 1`, PRQ-16's warning; one job at a time per self-hosted GitHub runner). One installed version per user
  stays (D13).
- **A repository's `.kiro/settings/cli.json`** overrides the global value for an implementer whose working directory is
  the worktree [D], so a repository could turn Kiro's self-update back on for its implementer steps. D10's check at the
  next job catches the drift.
- **The digests are the vendor's published values.** Task 1.1 recomputes the pin's four over the bytes before they ship.
- **The CDN answers 403, not 404, for a version it does not serve** [V]. A withdrawn version held in `KIRO_SHA256`
  therefore fails `doctor --ci --fix` with `HTTP 403` and the text above, never with a silent fallback.
- **A downgrade by Claude's native installer** (the pin below a newer native install) is [U]. The exact check of D5 makes a
  refused downgrade a `failed` action naming both versions; `npm install --save-exact` replaces the prefix's version
  either way [I].
- **`check_for_update_on_startup` on Codex 0.160.0** is [U]; task 3.1 checks it before the argv changes.
- **Every consumer's agent-CLI cache misses once** after the upgrade (the catalog gains the Kiro pin).

## Out of scope / follow-ups

- Kiro CLI 3 (a change of its own: record, then move the pin and the gate together).
- Harness-held digests for Claude Code (its signed `manifest.json` per version [D]) and for the npm CLIs.
- A private `KIRO_HOME` for read-only and `options.agent` steps (K5).
- `yolo_preflight.py` reading the effective pins (it keeps its own copy of the OpenCode pin).

## D13. Decisions taken in review (formerly the open questions; decided by the owner's delegate, 2026-10-20)

1. **No per-version install directories in 0.4.20.** One installed version per runner user; revisit only if a shared
   runner reports flips. Why: the vendor's layout and the agent-CLI cache paths stay as they are, and one job per
   runner user is already the rule.
2. **No team-supplied sha256 for a Kiro version outside `KIRO_SHA256`.** Why: a digest that ships with the harness is
   the only anchor a changed download cannot move; a digest in the repository's config is set by the same people who
   could change what is downloaded. A team that needs another version installs it and declares it (D9).
3. **No update switch on `codex app-server`**, unless task 3.1 shows that it checks for updates. Why: the documented
   key concerns the client's startup check, and an unrecognised `-c` on the zero-token probe would cost a failing
   probe for no evidence of benefit.
4. **No major gates for Claude Code or Codex in this change.** Why: L4-OCG-001's note stands; a gate needs recorded
   evidence that the next major breaks the adapter, which exists for Kiro CLI 3 [D] and not for them.
