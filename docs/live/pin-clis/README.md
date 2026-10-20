# pin-clis: live and download evidence

## 1.1 The four Kiro CLI 2.32.0 Linux archives (2026-10-20)

Each zip was downloaded once from `https://prod.download.cli.kiro.dev/stable/2.32.0/<file>` into a scratch directory
outside the repository, hashed over its bytes with sha256, opened with `zipfile` (nothing extracted, nothing run) and
deleted. The digests equal the table of design D1 (`KIRO_SHA256["2.32.0"]`).

| file | size (bytes) | sha256 | equals the table |
|---|---|---|---|
| `kirocli-x86_64-linux.zip` (`linux-x64`) | 154980622 | `7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb` | yes |
| `kirocli-aarch64-linux.zip` (`linux-arm64`) | 149913331 | `f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848` | yes |
| `kirocli-x86_64-linux-musl.zip` (`linux-x64-musl`) | 159551360 | `f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485` | yes |
| `kirocli-aarch64-linux-musl.zip` (`linux-arm64-musl`) | 151681117 | `219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b` | yes |

Members under `kirocli/bin/` (uncompressed size in bytes; every file is a regular file, Unix mode 0755; the directory
entry `kirocli/bin/` is mode 0755 and not a file):

| archive | `kiro-cli-term` | `kiro-cli` | `kiro-cli-chat` | `qchat` | `q` |
|---|---|---|---|---|---|
| `linux-x64` | 34060512 | 43931168 | 207496744 | 70 | 65 |
| `linux-arm64` | 31570352 | 40873568 | 196866944 | 70 | 65 |
| `linux-x64-musl` | 34290000 | 44154376 | 211260552 | 70 | 65 |
| `linux-arm64-musl` | 29956304 | 38808976 | 195715560 | 70 | 65 |

The harness extracts only `kiro-cli-term`, `kiro-cli-chat` and `kiro-cli`; the largest is 211260552 bytes, under the
512 MiB bound of `KIRO_MEMBER_MAX`.

## Task 3.1: Codex 0.160.0 and the update switch (2026-10-20)

Setup: `@openai/codex@0.160.0` installed with npm into a scratch prefix; empty scratch `HOME`, empty `CODEX_HOME`,
environment reduced to `PATH`, `HOME` and `CODEX_HOME` (no credential variable of any kind). The scratch install was
deleted afterwards. `codex --version` printed `codex-cli 0.160.0`.

1. `codex exec --skip-git-repo-check --ephemeral -s read-only -c check_for_update_on_startup=false -` with `x` on
   stdin, 60 s timeout: exit 1, stdout empty. stderr shows the session banner (model, sandbox read-only), then only
   `401 Unauthorized ... Missing bearer or basic authentication in header` from `api.openai.com/v1/responses`
   (websocket, then HTTPS, five reconnects each). No configuration error and no mention of the key: accepted.
2. Control, same command with `-c check_for_update_on_startup=notabool`: exit 1, stderr
   `Error loading config.toml: invalid type: string "notabool", expected a boolean in check_for_update_on_startup`.
   So the key is known to 0.160.0 and typed as a boolean; `false` is a valid value.
3. `codex app-server` with stdin closed, 20 s timeout: exit 0 at once, stdout and stderr both empty. No update
   check, and no mention of an update. (`codex app-server --help` lists `daemon`, `proxy`, `generate-*`; no update
   option.) Result: D13 decision 3 holds, `app-server` gets no switch.

## 6.1 Live run (2026-10-20)

**Verdict: every assertion of task 6.1 held except one: the job log never names the archive URL** (finding 1). The
install is verified by the exact version in the log and by the digest check in the code. Also, on a cold cache the
doctor's ENV-015 passes before the install, without having seen a CLI (finding 2). Labels: [V] observed in these runs or
read in the code at the live commit, [I] inferred from those.

Venue: the owner's dummy repository (public, throwaway), GitHub-hosted `ubuntu-24.04`, action delivery. The setup action
was pinned to the snapshot branch `live/pin-clis` (`9e741d01`: release 0.4.19 plus this branch's tree, the same tree as
`d26aca79` [V]). The profiles in role chains were `claude-impl` (claude-code, `roles.implementer`) and `kiro-sonnet`
(kiro-cli, `roles.judges`, `min_version: "2.32.0"`). The secrets came from the repository's `l4` environment. No job ran
`kiro-cli whoami` [V: no `whoami` in any log]. The doctor step had no `--live`, and the one unit the `run` step
touched stopped at the vendor rule before any probe (below).

Changes on the dummy (each commit carried `[skip ci]`, and none started a run [V]):
1. `l4 upgrade --harness-ref live/pin-clis` changed three things in `l4.yml`. It moved the `uses:` pin from `26332393`
   (`live/kiro-judge`) to `9e741d01` (`live/pin-clis`) and added the `job start` step. It also set the doctor step back
   to the generated `l4 doctor --ci --fix`, because the kiro-judge test had hand-edited it to `--live`. As a result,
   these runs made no probe or hello call [V: no `hello`, `probe`, `availability.` or `list-models` in any
   log].
2. Before run 3: `ci.cli_versions: {kiro-cli: "2.28.0"}`, and `kiro-sonnet`'s `min_version: "2.32.0"` removed.
   Otherwise the floor sits above the held version, and D9 makes the install `skipped`. This change was reverted after
   run 4. The dummy stays pinned to `live/pin-clis` with no override.

Cache keys were computed before the runs with `l4 ci cache-key clis` from this branch:
- `b6e0dba16c03422a` without an override, and `31692888944e55ab` with 2.28.0 held.
- The same hash document without `agent:kiro-cli` gives `cb78623b038d88a1`, the key the 0.4.18 runs saved. The Kiro
  pin is the only difference, so run 1 started with a cold agent-CLI cache [V].
- The runner's keys matched these values [V].

| # | Run / job | Config | Result |
|---|---|---|---|
| 1 | 39435335145 / 118670760528 | catalog pins | success: no agent-CLI cache; Claude Code and kiro-cli installed; cache saved (275000972 B) |
| 2 | 39435753594 / 118672201543 | catalog pins | success: cache restored (`~262 MB`), nothing installed, the save step skipped |
| 3 | 39435998595 / 118673052106 | kiro-cli 2.28.0 held | success: new key, no cache; kiro-cli 2.28.0 installed; cache saved (281137712 B) |
| 4 | 39436306234 / 118674123638 | kiro-cli 2.28.0 held | success (an extra run, for ENV-015, finding 2): cache restored, nothing installed |

Log lines (verbatim, timestamps and table padding removed):

```
run 1  Cache not found for input keys: l4-clis-Linux-X64-ubuntu24-b6e0dba16c03422a
       [l4] provision: installing claude
       [l4] provision: saved installer https://claude.ai/install.sh sha256=3a68d3406cf674e17bed1733a4dcf37805e2e47d87417700007d7e1aa766a944
       [l4] provision: installing kiro-cli
       ENV-004 error pass 2 agent CLI(s) present
       ENV-015 warn pass no agent CLI to compare with its pin
       fix  claude  applied  claude 2.1.288
       fix  kiro-cli  applied  kiro-cli 2.32.0
       Cache saved with key: l4-clis-Linux-X64-ubuntu24-b6e0dba16c03422a
run 2  Cache hit for: l4-clis-Linux-X64-ubuntu24-b6e0dba16c03422a
       ENV-015 warn pass claude 2.1.288, kiro-cli 2.32.0 at their pins
       fix  claude  already present  claude 2.1.288
       fix  kiro-cli  already present  kiro-cli 2.32.0
run 3  Cache not found for input keys: l4-clis-Linux-X64-ubuntu24-31692888944e55ab
       [l4] provision: installing kiro-cli
       CFG-011 warn fail kiro-sonnet: the judge invocation was measured on kiro-cli 2.32.0; kiro-sonnet: tool-less harness agent, …
       ENV-015 warn pass no agent CLI to compare with its pin
       fix  kiro-cli  applied  kiro-cli 2.28.0
       Cache saved with key: l4-clis-Linux-X64-ubuntu24-31692888944e55ab
run 4  Cache hit for: l4-clis-Linux-X64-ubuntu24-31692888944e55ab
       ENV-015 warn pass claude 2.1.288 at its pin; kiro-cli 2.28.0 held by ci.cli_versions; L4 pins 2.32.0
       fix  kiro-cli  already present  kiro-cli 2.28.0
```

Runs 2 and 4 have no `installing` line [V].

The CFG-011 warning in runs 3 and 4 is L4-KJD-009's expected warning for a Kiro judge with no `min_version`.

Findings:
1. **The job log does not name the Kiro archive URL** [V]:
   - `_install_kiro` downloads the archive without a log line. Claude's installer, by contrast, gets
     `saved installer <url> sha256=…`.
   - The doctor's fix report prints commands only for `manual` and `failed` actions.
   - None of the four logs contains `kiro.dev`, `latest` or `cli.kiro.dev/install` [V: grep].
   - Evidence that the versioned archive was installed:
     - `applied` means `_install_kiro` returned, which happens only after `verify_sha256` against
       `KIRO_SHA256[version]["linux-x64"]` [I: code].
     - `git grep latest` at `9e741d01` finds nothing in `src/l4/provision/` [V].
     - Run 3 installed 2.28.0, which `latest` does not serve (it serves 2.32.0, D1), and that install passed the 2.28.0
       digest [I].
   - A log line naming the URL (like Claude's `saved installer`) would make this check verifiable from the log alone.
     That is a decision for the orchestrator. Nothing was patched.
2. **On a cold cache, ENV-015 passes without having seen a CLI** [V]:
   - Doctor runs its checks before the fix.
   - `apply_fixes` re-runs only the checks that failed (`rerun = {o.id for o in outcomes if o.status == "fail"}`).
   - In a job that installs the CLIs, ENV-015 ran while no CLI was present and kept its pass,
     `no agent CLI to compare with its pin` (runs 1 and 3).
   - The install itself checks the version exactly (`_verified`; Kiro always, other CLIs under `--ci`).
   - The real comparison shows on the next run: run 2 for the catalog pins, and run 4 (an extra run with no agent
     calls) for the held 2.28.0.
3. The `run` step retried the unit that the kiro-judge negative leg had left in `waiting_capacity` [V]:
   - It was refused at the vendor rule (the judge and the implementer share the vendor) before any probe.
   - Exit 12 within 8 to 15 s, with no agent call. The unit's branch got a merge of main (runs 1 and 3) and a ledger
     commit (every run).
   - No continuation run was dispatched [V: runs list]: exit 12 is not `deferred` [V: code].

Account-data scan, after each run, over the full job log:
- Searched for e-mail addresses (`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`), `whoami` and an `"email"` key.
- Nothing was found in any of the four runs, so no log was deleted [V].
- These notes hold only run and job ids, cache keys, versions and public digests. There is no secret to redact.
