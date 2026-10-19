Every task group is one implementer step. Each step follows these rules:
- Read `proposal.md`, `design.md` and `specs/agent-cli-major/spec.md` of this change first, and
  `docs/plan/opencode-v2.md` rows 1–5 for the evidence.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>` and `.venv/bin/ruff format --check <changed files>`.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `opencode-major-gate A<n>: …`,
  with no trailer and no local path.
- Never write a `while pgrep …` loop or any loop that waits on a process name. Run commands in the foreground with a
  timeout.
- Name no consumer repository. Write "a consumer repository" when one is meant.
- Fixture files hold no local path: before committing one, `grep -rnE '/private/|/Users/|/home/[a-z]|/var/folders/'` and
  `grep -rn "$USER"` over it must print nothing.

## 1. Group A1: the major gate in the probe, the hello and the run (L4-OCG-001, -002 probe part, -003)

Depends on: nothing. Its commit is the base of group A2.

- [x] 1.1 Fixtures. Create `tests/fixtures/cli_major/opencode/` with these files, byte for byte (they were recorded
  in an isolated HOME; none holds a path):
  - `v1-1.18.34.version.txt`: `1.18.34\n`
  - `v2-2.0.32.version.txt`: `opencode v2.0.32\n`
  - `v2-2.0.32.run-pure.stderr.txt`: `\nERROR\n  Unrecognized flag: --pure in command opencode run\n`
  - `v2-2.0.32.run-dir.stderr.txt`: `\nERROR\n  Unrecognized flag: --dir in command opencode run\n`
  - `v2-2.0.32.run-help.stdout.txt`: the run help that v2 prints on stdout with that error. The orchestrator passes the
    recorded file's directory as `OC2_RAW`. Copy `$OC2_RAW/v2-hello-pure.jsonl` to this name, then check it starts
    with `DESCRIPTION` and holds `Unrecognized` nowhere.

  Do not create anything under `tests/fixtures/recorded/`, and do not regenerate `src/l4/recorded_versions.json`.
- [x] 1.2 Tests first, `tests/unit/test_versions_major.py` (SCN-OCG-01): `major_of` on both fixture files gives 1 and
  2, and gives None for `""` and `"no version here"`. `catalog.SUPPORTED_MAJORS == {"opencode": 1}` and equals
  `parse_version(OPENCODE_VERSION)[0]`. `catalog.major_problem("opencode", "opencode", "opencode v2.0.32", "1.18.34")`
  equals exactly `opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34
  (l4 doctor --fix installs it user-locally) or set options.cli_major: 2 when supported`. It returns None for
  `1.18.34`, None for an adapter not in the table (`codex`), and None for text with no version.
  Code: `src/l4/versions.py` (`major_of(text) -> int | None`, from `parse_version`) and `src/l4/provision/catalog.py`
  (`SUPPORTED_MAJORS`, `major_problem(adapter, binary, version_text, pin) -> str | None`).
- [x] 1.3 Tests first, in `tests/unit/availability/test_probes_opencode.py` (new tests, the existing ones unchanged
  except where a `detail ==` equality must now include `major`):
  - SCN-OCG-03: the `binary` step with `--version` answering `opencode v2.0.32` fails with the exact reason from 1.2.
    The `hello` step with the same version also fails at `binary`, and the fake runner records no `run` call.
  - SCN-OCG-02: the same with no `min_version`, and with `min_version: "1.18.0"`, both fail.
  - A pass carries `detail["major"] == 1`.
  Code: `src/l4/availability/probes.py` `_binary`. Check the major first, independent of `min_version`, using
  `major_problem` with `catalog.ADAPTER_PINS`. Only adapters in `SUPPORTED_MAJORS` are gated, so the claude and codex
  probe tests must still pass unchanged.
- [x] 1.4 Tests first, `tests/unit/availability/test_hello_failure_class.py` and
  `tests/unit/availability/test_failure_ttl.py` (SCN-OCG-06):
  - The opencode hello whose fake runner returns exit 1, stdout = `v2-2.0.32.run-help.stdout.txt` and stderr =
    `v2-2.0.32.run-pure.stderr.txt` fails with `failure_class == "unsupported_version"` and a reason starting
    `unsupported_version:`. The binary step of that test answers `1.18.34`, which simulates a binary swapped after
    the probe.
  - Exit 1 with an empty stderr is still `transient`.
  - `FallbackSelector._remember` stores no entry for an `unsupported_version` hello failure.

  Code: `src/l4/agents/base.py` (`FailureClass` gains `"unsupported_version"`), `src/l4/agents/opencode.py` `_hello`
  (read `done.stderr`; the pattern `Unrecognized flag: --(pure|dir)\b` is checked before the
  `exited with code` branch), and `src/l4/availability/fallback.py` `_remember` (no behaviour change, since only
  `other` and `auth` are stored; extend the docstring to say `unsupported_version` is not stored, like `transient`).
  Grep for other exhaustive uses of `FailureClass` (`rg "failure_class|FailureClass" src/l4`) and make each handle
  the new member.
- [x] 1.5 Tests first, in `tests/unit/agents/test_opencode.py` (SCN-OCG-07):
  - `OpenCodeAdapter().parse(lines_of(run-help.stdout), exit_code=1, stderr_tail=<run-dir.stderr>, …)` gives status
    `error` and a detail starting `unsupported_version:` that contains `opencode --version`. `parse` gains the
    keyword `stderr_tail: str = ""`.
  - The same without `stderr_tail` keeps today's detail `opencode exited with code 1`.
  - `run()` passes the last 8 KiB of `raw_events_path.with_suffix(".stderr")`. Test it with the existing fake
    `ProcRunner` pattern of the file.

  Code: `src/l4/agents/opencode.py` (`run`, `parse`).
- [x] 1.6 Run `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_versions_major.py
  tests/unit/availability tests/unit/agents/test_opencode.py tests/unit/agents/test_opencode_key.py
  tests/unit/agents/test_opencode_provider.py tests/unit/doctor/test_live_005.py`, then `ruff check` and
  `ruff format --check` on the changed files. Commit.

  Done when: every test above passes, no existing test was weakened, and `git diff --stat` shows only the files
  named in 1.1–1.5.

## 2. Group A2: doctor, provisioning, prereqs.sh and the docs (L4-OCG-002 doctor part, -004)

Depends on: group A1 (`major_of`, `major_problem`, `SUPPORTED_MAJORS`).

- [x] 2.1 Tests first:
  - `tests/unit/doctor/test_checks_env_004.py` (SCN-OCG-04, SCN-OCG-02): an implementer chain whose only `opencode`
    profile has no `min_version`, with `ctx.run` answering `opencode v2.0.32`. ENV-004 fails with severity `error` and
    a message holding the reason from 1.2. With a second, usable profile in the chain, it fails with severity `warn`
    and names the usable fallback (the existing chain rule).
  - `tests/unit/doctor/test_live_005.py` (SCN-OCG-05): a v2 answer gives `fail` with `severity == "error"`, the
    reason, and no `unrecorded version` text. A v1 patch drift (`1.18.35`) still gives the existing warning.

  Code: `src/l4/doctor/checks_env.py` (`_cli_problem`: for an adapter in `SUPPORTED_MAJORS`, always run `--version`
  and return `major_problem(...)` first) and `src/l4/doctor/checks_agents.py` (`_live_005`: the major check before
  `recordedversions.unrecorded`; a wrong major is a separate `CheckResult("fail", …, severity="error")`). ENV-004
  takes the adapter, so pass it in. The registry already lets a result raise its check's severity: `registry.py` uses
  `result.severity or check.severity`. Assert that the doctor run's report is not `ok` for the LIVE-005 error case, and
  is still `ok` for the patch-drift warning.
- [x] 2.2 Tests first, `tests/unit/provision/test_plan.py` and `tests/unit/provision/test_install.py` (SCN-OCG-08,
  SCN-OCG-09):
  - `is_satisfied` is False for the opencode `ToolSpec` with found `2.0.32`, and True for `1.18.34`.
  - `plan_fixes` gives `planned` with reason `found 2.0.32 (OpenCode v2), need opencode-ai 1.x (pinned 1.18.34)`.
  - `install_planned` with the fake npm runs `npm install --prefix <l4_home>/npm … opencode-ai@1.18.34`, links
    `~/.local/bin/opencode`, and verifies the major: the fake `--version` answers `1.18.34` after the install.
  - A regular file at `~/.local/bin/opencode` stays byte-identical, and the action is `failed` with a message naming
    that path and the manual command.
  - A regular file at `~/.local/bin/node` is still replaced by the Node install, as today. Pin it so the guard stays
    scoped.
  - When `--version` still answers `opencode v2.0.32` after the install, the action is `failed`, naming the resolved
    path.

  Code: `src/l4/provision/runner.py` (`is_satisfied`, and the reason text in `plan_fixes`) and
  `src/l4/provision/install.py` (`_link(target, link, *, replace_files=True)` raises `InstallFailed` for a
  non-symlink existing path when `replace_files` is False; `_install_agent` passes False only for an adapter in
  `SUPPORTED_MAJORS`; `_verified` checks `major_problem`). Use `tests/unit/provision/_install_helpers.py` for the fakes.
- [x] 2.3 Tests first, `tests/unit/runner/test_prereqs_steps.py` (SCN-OCG-10). These are static plus small bash
  evaluations, and the script itself never runs:
  - `check_opencode`'s body strips an optional `opencode v` prefix and requires major 1. Extract the function with a
    regex and run it in `bash -c` with a stub `as_runner` that echoes `opencode v2.0.32`, which must return non-zero
    with DETAIL holding `need 1.x >= 1.18.34`, then `1.18.34`, which must return 0.
  - The PRQ-15 opencode line calls `opencode models` only inside a branch on `check_opencode`.
  - `bash -n` still passes.

  Code: `scripts/runner/prereqs.sh` (PRQ-11 `check_opencode`, the PRQ-15 `auth: opencode` line). The FAILED DETAIL
  after an apply names `$(as_runner 'command -v opencode')`.
- [x] 2.4 Docs (no test file; run `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, which must exit 0):
  - `docs/SPEC.md`: add **L4-OCG-001…004** (the requirement texts of `specs/agent-cli-major/spec.md`, as SPEC
    requirements in §8.3 after L4-FAC-007), and SCN-OCG-01…10 in Part II next to SCN-FAC-14. Use the Part II form
    `#### SCN-OCG-01 (+) <title> · L4-OCG-001` with **Given**, **When**, **Then**.
  - L4-FAC-007: append the sentence "A CLI whose major version differs from the adapter's supported major is refused
    at the `binary` step with a named reason (L4-OCG-002); only a patch drift within the supported major runs with
    the `unrecorded version` warning."
  - §8.3 `opencode` row: append "The major of `opencode --version` (`1.18.34` or `opencode v2.0.32`) must be 1
    (L4-OCG-001…004)." Edit only that row's line.
  - The change table: add the row `| 51 | \`opencode-major-gate\` | an \`opencode\` whose \`--version\` is not major 1
    (OpenCode v2 prints \`opencode v2.0.32\` and rejects \`--pure\` and \`--dir\`) is refused by name at the probe's
    \`binary\` step, by doctor ENV-004 and LIVE-005 (an error, never a warning) and by \`prereqs.sh\` PRQ-11, whether
    or not \`min_version\` is set; a rejected flag at a hello or run is \`unsupported_version\`, never \`transient\`
    and never cached; \`doctor --fix\` installs the pinned v1 instead and never replaces a regular file
    (L4-OCG-001…004; \`openspec/changes/opencode-major-gate/\`) | a runner with OpenCode v2 as \`opencode\`: the
    profile is skipped at \`binary\` with the reason, and \`l4 doctor --fix\` makes it pass |` as its own new line
    after the highest existing row. The `kiro-judge` change adds row 50 at the same place, so do not edit any other
    row.
  - `CHANGELOG.md`: if `## 0.4.20 (unreleased)` is missing, add it above the newest heading, with `### Changed` and
    `### Fixed`. Add separate lines. Changed: the opencode major gate (the reason text) and the provisioning
    behaviour. Fixed: PRQ-11 accepted `opencode v2.0.32`, the v2 hello failure was `transient`, and `doctor --fix`
    kept a v2 `opencode`.
  - `docs/runbook.md` §7.4: add a bullet under **Causes** and a short procedure "OpenCode v2 on the runner": the
    reason line, `opencode --version`, `l4 doctor --fix` (or `npm install --prefix ~/.local/share/l4/npm
    opencode-ai@1.18.34`), then `l4 probe <profile> --role <role> --no-cache`.
- [x] 2.5 Run `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/doctor tests/unit/provision
  tests/unit/runner tests/unit/test_recorded_versions.py`, `scripts/check_spec.py docs/SPEC.md`, and the ruff checks
  on the changed files. Commit.

  Done when: all pass, `src/l4/recorded_versions.json` is unchanged, and no row of the change table except the new
  row 51 changed.
