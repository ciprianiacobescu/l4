## Context

The analysis is `docs/plan/opencode-v2.md`, rows 1–5 and 8. Every fact this change rests on is [V], recorded in an
isolated HOME with `opencode-ai@1.18.34` and `@opencode/cli@2.0.32` installed side by side, or read in the code:

- `opencode --version` prints `1.18.34` (v1) and `opencode v2.0.32` (v2) [V].
- `opencode run --pure …` and `opencode run --dir …` on v2: stderr `\nERROR\n  Unrecognized flag: --pure in command
  opencode run\n` (or `--dir`), stdout the run help text, exit 1 [V].
- `l4.versions.parse_version("opencode v2.0.32") == (2, 0, 32)` [V code: the `(?<=\bv)` branch of the regex].
- `probes._binary` and `checks_env._cli_problem` skip the version comparison when `min_version` is unset [V code].
- `prereqs.sh` `ver_ge "opencode v2.0.32" 1.18.34` is true [V: `sort -V` orders `1.18.34` first].
- `runner.is_satisfied` for an agent is `min_version is None or found >= min_version` [V code].
- v2's `models`, `auth list` and `debug config` start a shared per-user daemon that outlives the client [V].

## Decisions

**D1. One function, one table.** `l4.versions.major_of(text) -> int | None` returns the major of the first version
`parse_version` finds. `l4.provision.catalog.SUPPORTED_MAJORS = {"opencode": 1}` is derived from the pin
(`parse_version(OPENCODE_VERSION)[0]`), so moving the pin to a new major moves the gate with it. Only the `opencode`
adapter is listed. Claude Code updates itself and Codex is 0.x, so gating them would be a separate decision with its
own evidence. `catalog.major_problem(adapter, binary, version_text, pin) -> str | None` builds the one reason text
every caller prints. The change `opencode-v2` later passes the profile's `cli_major` in place of the table's value.

**D2. The reason is one sentence a person can act on.** It names the found version, the found major, what the profile
runs, the pinned package, and both ways out:

`opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 (l4 doctor --fix
installs it user-locally) or set options.cli_major: 2 when supported`

The probe, ENV-004, LIVE-005 and the `doctor --fix` reason all print this text.

**D3. Checked on every read, whatever `min_version` says.** `_binary` already runs `--version` for every profile, but
compares only under `min_version`. The major comparison comes first and does not depend on it. `_cli_problem`
(ENV-004) returns early without `min_version` and so never runs `--version`. For a gated adapter it now always runs
`--version`. LIVE-005 checks the major before the recorded-version comparison and returns `fail` with `severity="error"`
for a wrong major. A wrong major is a misconfiguration, never "a newer patch that may still parse".

**D4. `unsupported_version` is a failure class, not a reason string.** `FailureClass` gains `"unsupported_version"`.
The hello maps "exit ≠ 0 and stderr matches `Unrecognized flag: --(pure|dir)\b`" to it, before the existing
`opencode exited with code N` → `transient` branch. The class is not remembered in the probe cache. `_remember` stores
only `other` (for `cache_ttl`) and `auth` (for `auth_failure_ttl`). The comment and a test now state that
`unsupported_version` is intentionally not stored, like `transient`, so that installing v1 takes effect at the next
probe. What changes from `transient` is what a person reads. The hello's reason begins `unsupported_version:`
(`unsupported_version: opencode rejected --pure: the binary on PATH is not OpenCode v1 (run opencode --version)`), so
the skip line `[l4] <role>: <profile> skipped — hello: unsupported_version: …` shows it, and `l4 probe --json` carries
`failure_class: unsupported_version`. The run path reads the stderr file the adapter already writes
(`raw_events_path.with_suffix(".stderr")`). `parse()` gains a keyword `stderr_tail: str = ""` (the last 8 KiB), and
`run()` passes it. An exit ≠ 0 with no `error` event and that stderr gives status `error` with the detail
`unsupported_version: opencode rejected --pure: the binary on PATH is not OpenCode v1 (run opencode --version)`. In
normal operation the `binary` step stops such a profile first. This branch catches a binary swapped between the probe
and the run, and pins the recorded stderr.

**D5. Provisioning replaces, but never destroys.** `is_satisfied(tool, found)` returns False for an agent listed in
`SUPPORTED_MAJORS` whose found major differs, so `plan_fixes` plans the pinned install with the reason
`found 2.0.32 (OpenCode v2), need opencode-ai 1.x (pinned 1.18.34)`. The install is today's: `npm install --prefix
$L4_HOME/npm opencode-ai@1.18.34` and a link `~/.local/bin/opencode`. `_link` gains a keyword `replace_files: bool =
True`. `_install_agent` passes `False` for an adapter in `SUPPORTED_MAJORS`, and only there: an existing path that is
neither missing nor a symlink is then never replaced, and the action fails naming the path and the manual command,
because a regular file there may be a person's own v2 binary. The Node links (`node`, `npm`, `npx`), `laya-serve` and
the codex link keep today's behaviour. `_verified` checks the major of the binary that `find_tool`
resolves on the harness path. When it is still wrong (a v2 earlier on the harness path), the action fails naming the
resolved path. The harness path puts `~/.local/bin` first [V code: `harness_path`], so the v1 link wins inside the
harness. The runner's login PATH, which `prereqs.sh` uses, may still find v2 first. PRQ-11 reports that case as FAILED
with the path.

**D6. PRQ-11 and PRQ-15.** `check_opencode` reads `opencode --version | tail -1`, strips an optional `opencode v`
prefix, and passes only when the major is 1 and `ver_ge` holds. Its DETAIL names the version, the resolved path and
`need 1.x >= 1.18.34`. PRQ-15 computes the free-model count with `opencode models` only when `check_opencode` passes,
and otherwise prints `free models: skipped (opencode at <path> is not OpenCode v1)`, because v2's `models` starts the
shared daemon that outlives the call.

**D7. Fixtures stay out of the recorded tree.** The two `--version` outputs and the rejected-flag stdout and stderr are
copied verbatim (they hold no path) to `tests/fixtures/cli_major/opencode/`. `recordedversions.generate` scans only
`tests/fixtures/recorded/<tool>/<version>/`, so nothing here makes 2.0.32 "recorded" for the v1 adapter.
`opencode-v2` creates `tests/fixtures/recorded/opencode/2.0.32/` together with the per-major LIVE-005 comparison.

## Risks

- A runner that deliberately runs v2 as `opencode` (no harness use) now gets v1 linked at `~/.local/bin/opencode` by
  `doctor --fix`. This is what the harness needs, it is user-local, and a regular file is never replaced. The runbook
  entry says how to keep both: v2 as `opencode2` (change B).
- A future v1 that drops `--pure` would read as `unsupported_version` at the hello. The text names the flag, so a
  person sees the cause.
