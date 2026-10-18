# Guard harness writes: no write through a planted link, gate and runner configuration put back, masked agent folders protected

Status: design, 2026-10-17. Harness at 0.4.14 (`795e97a9`). Markers: **[V]** verified, meaning read in the code at the
cited place or run in this worktree; **[I]** inferred, meaning it follows from the code and was not run end to end.

## 0. The answer in brief

1. Every write, read and removal that the harness makes in a worktree after agent code ran goes through new primitives
   in `l4.fsutil`. These primitives walk the path with directory descriptors and never follow a link (`O_NOFOLLOW` on
   every component). A file is written as a new file and then renamed over its name. A link on the path raises
   `LinkedPath`. The caller records it, removes the link and writes once more. No exception leaves a `finally` (D1–D4).
2. A recorded `planted link` halts the unit at once, like `secret_in_push`: the attempt is discarded, `PlantedLink` is
   raised (never out of a `finally`), and the orchestrator trips `breaker.tripped{reason: planted_link}` with the
   evidence and halts the unit for a person (owner decision 1, D4). A recorded `restore failed` fails the implementer
   attempt at the next check before its commit. In the verifier, both are a blocker. The run always goes on (D4).
3. `restore_to_base` removes links at or above its path, checks out a former directory whole, and runs `git rm -r
   --cached` for a path that is new. `ProductionGuard.check` records a link at a production path instead of crashing
   (D5).
4. Gate and runner configuration have exact definitions (D6). A guard runs after every agent step, against the step
   base, and after every gate run, against the state just before the gate. It puts the whole file back when a guarded
   *section* differs, compared parsed (D7). Changes are allowed by a `[config]` or `[test-infra]` tag, or by a person's
   answer (`task.config_opened`). The red-to-green runner freeze is never lifted (D8). The verifier checks the same rule
   on the commits (D9).
5. `.hermes/**`, `.kiro/hooks/**`, `.kiro/prompts/**` and `.kiro/skills/**` are added to the contract list, and
   `.kiro/skills` to `sandbox.base.GUIDANCE_DIRS` (owner decision 4). A drift test keeps every directory in
   `GUIDANCE_DIRS` protected (D10).

## 1. Current state (0.4.14)

- The three findings reproduce in this worktree [V]. The ported `test_verify_impl1_symlink.py` and
  `test_verify_impl3_config.py` give 7 passed, run against `src/l4` of this worktree. `r3_protected_guard.py` prints
  `not protected by ProtectedSet.match: ['.hermes', '.kiro/hooks', '.kiro/prompts']`, and all three paths are staged by
  `git add -A`.
- Write sites that follow a planted parent link [V, read]:
  - `implementer/discrimination.py`: `zero_values_in_place` (the variant write at `:81`, the restore at `:87`, the
    sha256 read-back at `:89`, the `RuntimeError` at `:92`) and `_drop_bytecode` (`:46`, a glob and an unlink in
    `<parent>/__pycache__`).
  - `discrimination.py`: `zeroed_run` restores reports at `:106-110`. `red_code_in_place` writes or unlinks at
    `:135`, `:137` and `:143`. `run_with_code_of` restores reports at `:186-190`.
  - `gates/runner.py:150-151`: `path.unlink(missing_ok=True)` of each report before the gate. `:172-178`: the report
    is read through a linked parent. `read_regular_file` refuses only a link as the last component.
  - `implementer/stubs.py`: `restore_to_base` (`:687-698`). `unlink` of a target whose parent is a link. When a link
    replaced a directory, `existed=False` and `git rm --cached` without `-r` raises `GitError` (exit 128). That is the
    crash the reviewer saw.
  - `stubs.py:740`: `enforce_red_scope` writes the rebuilt file.
  - `stubs.py:814-820`: `ProductionGuard.check` runs `unlink`, `parent.mkdir` and `write_bytes` through a linked
    parent.
  - `verifier/audit.py:234,243,342`: unlinks of the audit test files after gates.
- `_is_inside` (`stubs.py:671`) refuses only a link as the last component and a path that resolves outside the
  worktree. It is called before the gate, so the check and the write are separate (time of check, time of use). It
  lets an in-tree link through, for example `src/pytdd -> ../tests`.
- Already safe [V, read]:
  - `security/protected.py`: `restore_protected` unlinks the first linked ancestor before `_write`, and `_put_back`
    passes `-r`. These are the pattern for this change.
  - `git checkout <rev> -- <path>` over a symbolic link at a leading directory removes the link and recreates the
    directory, and the outside file is untouched. `git clean -fdxq -e .l4-out/` removes a planted `.l4-out` link,
    because a `dir/` pattern does not match a link. Both were run on git 2.x in the scratch directory [V].
- Platform facts, probed with this worktree's Python 3.12 on darwin [V]:
  - `os.open(name, O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=…)` on a directory link fails with `ENOTDIR`, not
    `ELOOP`. On a file link it fails with `ELOOP`.
  - `os.rename(src, dst, src_dir_fd=fd, dst_dir_fd=fd)` replaces a link without touching its target.
    `os.replace in os.supports_dir_fd` is False, so use `os.rename`.
  - `os.open(..., O_NONBLOCK)` of a FIFO returns at once.
  - `shutil.rmtree.avoids_symlink_attacks` is True.
  - Linux has the same calls (`openat`, `renameat`, `unlinkat`, `mkdirat`) [I].
- Configuration [V, read]:
  - `tdd.gate_config_globs` (`config/defaults.py:40`) has no reader in `src/l4` except the schema.
  - `tdd.runner_config_files` makes whole files exempt from red scope (`stubs.py:678-684`).
  - `guards.py:7` lists `revert_gate_config` as M1.
  - The verifier compares runner sections red→green only (`integrity.check_freeze`). Its header says "Not built: …
    gate configuration and script entries (2.9)".
- Protected paths: `CONTRACT_PROTECTED_GLOBS` (`security/protected.py:31-44`) lacks `.hermes/**`, `.kiro/hooks/**`
  and `.kiro/prompts/**`. `GUIDANCE_DIRS` (`sandbox/base.py:121-124`) and `m0_guidance` of
  `scripts/runner/sandbox-probe.sh:51` list them [V].

## D1. Confined file primitives (`src/l4/fsutil.py`)

All paths are POSIX, relative to `root`, with no `..` and no leading `/` (`ValueError` otherwise). `root` itself is
opened normally, because the worktree's own absolute path may hold a link, such as `/var` → `/private/var`. Only the
components below `root` are opened with no-follow.

```python
class LinkedPath(UnsafeFile):
    """A component of a root-relative path is a symbolic link: nothing is read or written through it."""
    link: str  # the linked component, relative to the root (for example "src/pytdd")

def linked_component(root: Path, rel: str) -> str | None
    # lstat of every component of `rel` in order, the last one included; the first link, or None.
    # A missing component ends the walk (None).
def remove_link(root: Path, link: str) -> bool
    # unlinkat of exactly that component, relative to its parent's descriptor, if it is still a link.
    # Never follows it. True when removed.
def read_inside(root: Path, rel: str, *, limit: int) -> tuple[bytes, int] | None
    # (content, st_mode) of a regular file of at most `limit` bytes. None when it or a parent does not exist.
    # LinkedPath for a link at any component. UnsafeFile for a non-regular file or one that is too large.
    # Opened with O_RDONLY|O_NOFOLLOW|O_NONBLOCK, then checked with fstat.
def write_inside(root: Path, rel: str, data: bytes, *, mode: int | None = None) -> None
    # Missing parents are created with mkdirat (0o777, under the umask).
    # Writes `.{name}.l4tmp.{token_hex(4)}` with O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW (0o666, under the umask),
    # applies fchmod(mode & 0o7777) when `mode` is given, then renameat over `name`.
    # A directory at `name`: UnsafeFile("… is a directory"), with the temporary file removed.
def unlink_inside(root: Path, rel: str) -> bool
    # unlinkat of the last component: a file or a link, never a link's target.
    # False when it or a parent is absent. LinkedPath for a linked parent.
    # A directory at the name: UnsafeFile.
```

The internal walk `_parent_fd(root, rel, *, create)` opens each parent component with
`O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` and `dir_fd`. On `ELOOP` or `ENOTDIR` it lstats the component
(`os.stat(part, dir_fd=fd, follow_symlinks=False)`) and raises `LinkedPath` when the component is a link. Any other
error is re-raised. Every descriptor it opened is closed in a `finally`.

Why a directory descriptor walk and not a check followed by a write (the reviewer's "record the resolved parent and
compare"):

- The walk makes the check and the write one operation. A process that outlives the gate cannot win a race. Under
  bubblewrap, `--unshare-pid --die-with-parent` makes such a process unlikely [I], but `NoSandbox` on macOS has no such
  guard.
- The walk refuses an in-tree link, which `_is_inside` lets through. A compare of the resolved parent would refuse
  it too, but would still check and write as two separate steps.
- Rename instead of `O_TRUNC`: a hard link that a gate put in place of a varied file would otherwise get the original
  bytes written into the other inode. A FIFO would block the harness. Under bubblewrap a hard link across the
  read-only bind fails with `EXDEV`, so this is the `NoSandbox` case [I].

## D2. Targets are taken by their real path, resolved before the gate

`zero_values_in_place` and `red_code_in_place` canonicalize each target before they write the variant:

```
real = (root / rel).resolve()
rel = real.relative_to(root.resolve()).as_posix()
```

A target whose real path is outside the worktree, matches `tdd.test_globs` or `tdd.test_support_globs`, or is not a
regular file is skipped, as `_is_inside` skips it today. After the gate, only that link-free `rel` is written.

So a repository that commits `src/app -> ../lib/app` still has `lib/app/core.py` varied and put back
(SCN-SEC-48). Only a link that appears on the canonical path during the gate counts as planted.

Report paths and the paths that `ProductionGuard` and `restore_to_base` handle are not canonicalized:

- report paths come from the configuration, and `.l4-out` is the harness's own folder;
- the guard's paths come from git, which never lists a path below a link.

## D3. Write sites changed

| Site | Change |
|---|---|
| `discrimination.zero_values_in_place` | Read the original with `read_inside` and keep `(bytes, mode)`. Write the variant and each restore with the helper `_put(wb, rel, data, mode, where)`. The sha256 read-back uses `read_inside`. A mismatch is recorded as `restore failed` (D4), not raised. `_already_varied` stays: it uses `os.stat` of the canonical path. |
| `discrimination._drop_bytecode` | Takes `(root, rel)`. Opens `<parent>/__pycache__` with no-follow, lists it with `os.listdir(fd)`, and unlinks the matching `.pyc` names with `dir_fd`. A linked `__pycache__` is removed with `remove_link`. |
| `discrimination.red_code_in_place` | Same as `zero_values_in_place`. The set-aside of a module that green added uses `unlink_inside` before the gate, and the restore uses `_put`. |
| `discrimination.zeroed_run`, `run_with_code_of` | Keep each report as `read_inside` gives it. The restore calls `_put` for a kept report and `unlink_inside` for a new one. Any `UnsafeFile` goes to the record. |
| `gates/runner.run_gate` | Removing an earlier report uses `unlink_inside`. A `LinkedPath` there, or a `linked_component` of a report path found before the parse, returns `result("fail", "report path {rel} has a symbolic link at {link}")`: before the command runs in the first case, before any read in the second, the way `shadowing_plugin` fails. `dryrun.py` calls `run_gate` directly and gets the same protection. |
| `workbench.Workbench.run_gate_spec` | Before and after the gate, each report path with a `linked_component` goes to the record (D4). The link is removed, so the gate writes a real `.l4-out`. |
| `stubs.restore_to_base`, `enforce_red_scope`, `ProductionGuard` | D5. |
| `discrimination._put` | A link as the LAST component is found with `linked_component` before the write and goes to `refused_write`: the rename in `write_inside` would replace it without an error, and a leaf plant must be recorded and halt like every other (hard links and FIFOs stay a silent replace, SCN-SEC-44). |
| `verifier/generate.py` `_drop_generated` | The writer's UI test file is removed after agent-controlled e2e runs with `unlink_inside`; a planted `e2e` link is removed and recorded (`where: generate`), a blocker in the verifier (SCN-SEC-47). |
| `verifier/audit.py` | The three `(wb.worktree / rel).unlink(missing_ok=True)` calls become `unlink_inside`, and an `UnsafeFile` goes to the record. |

`_put(wb, rel, data, mode, where)`:

```python
try: write_inside(root, rel, data, mode=mode)
except UnsafeFile as exc:
    wb.refused_write(exc, path=rel, where=where)      # removes a link, records
    if isinstance(exc, LinkedPath):
        try: write_inside(root, rel, data, mode=mode)  # once more: the walk now makes real directories
        except UnsafeFile as again: wb.refused_write(again, path=rel, where=where)
```

The retry leaves the worktree as close to its state before the gate as it can be. The attempt still fails (D4), so a
repaired tree never passes for a clean one.

## D4. What a refused write records, and what fails

`Workbench` gets these members:

- `unsafe: list[UnsafeWrite]`, where `UnsafeWrite(path, rule, where, link, target)` is a frozen dataclass. The field sits next to
  `guard_notes`. `run_task` clears both at the start of every attempt.
- `refused_write(exc: UnsafeFile, *, path: str, where: str, root: Path | None = None) -> None` (`root`: the checkout the
  gate ran in, the worktree by default):
  - for a `LinkedPath`, it reads the link's target, calls `remove_link(root, exc.link)` and emits
    `guard.violation{phase: "gate", rule: "planted link", path: exc.link, action: "removed", where, target: path,
    points_to}`;
  - for any other `UnsafeFile`, it emits `guard.violation{phase: "gate", rule: "restore failed", path, action:
    "refused", where, why: str(exc)}`;
  - it appends an `UnsafeWrite` in both cases. The same link is recorded once per attempt. Every event carries `path`
    and `rule`, so `guardnotes.note_of` turns it into a note for the next prompt.
- `unsafe_reason() -> str`: `""` when `unsafe` is empty. For a planted link it returns: `a gate run put a symbolic link
  at <path>[, <path>…] (on the path of a file the harness restores); the harness removed it and wrote nothing through it.
  Nothing of this attempt is kept`. For `restore failed` only, it returns `the harness could not put <path> back after a
  gate run. Nothing of this attempt is kept`. At most 5 paths, then `(+N more)`.
- `planted_links() -> list[UnsafeWrite]`: the `planted link` records, with `link` and `target`.

Where the record ends the attempt. Each site calls `wb.discard_changes()` first. A `planted link` (owner decision 1)
raises `PlantedLink`; `restore failed` returns a failed outcome with `unsafe_reason()`. `tdd.stop_on_unsafe(wb)` does
both:

| Step | Site |
|---|---|
| red (`tdd.run_red`) | `tampered(where)` runs `guard.check(where)` and then `stop_on_unsafe`. It runs after every gate stage: the test run, the pre-satisfied confirmation, the base run, the restored test run, the vacuity check, the static gates, and before both commits (red and already-satisfied). |
| green (`tdd.run_green`) | `reason = stop_on_unsafe(wb) or reason` after the `reason or _undiscriminating(...) or worse_static_gates(...)` chain, so that it also covers `fails_at_red`. |
| single (`tdd.run_single`) | `reason = stop_on_unsafe(wb) or reason` after `_discriminating_tests`. |
| verifier (`ladder.verify_unit`) | When `wb.unsafe` is not empty, before `_finalize` and before the `else` branch's `aggregate_unit`, add one `Finding(Severity.BLOCKER, title, detail, "deterministic")` with the title `a gate run planted a symbolic link in the worktree` (or `could not restore a file after a gate run`) and the paths in the detail. The round ends FAIL; the verifier has no attempt to halt. |

`PlantedLink(reason, links)` sits beside `BaselineFailed` in `tdd.py`. `orchestrator._implement` catches it next to
`BaselineFailed`, appends `breaker.tripped{reason: "planted_link", task, links: [{path, points_to, where}]}` (at most 20
links) and calls `_halt("planted_link", f"task {task}: {exc}")`. The paths are at the front of the detail because the
`phase.changed` keeps 300 characters. `fixloop` catches it next to its `BaselineFailed` and returns
`FixOutcome("halt", reason, code="planted_link")`, which `Orchestrator._fix` turns into the same halt code. The code
`planted_link` joins the `halted` codes of L4-OPS-005, the table of `docs/runbook.md` and its §7.2.

What a person sees:

- the `guard.violation` events and `breaker.tripped{links}` in the ledger, where each link carries its target
  (`points_to`, read before the harness removed it);
- the halt reason in `l4 status`, the note on the pull request and `exit_reason`, with the paths at the front;
- for `restore failed`, `task.attempt_failed.reason` and, after `max_task_attempts`, the halt reason;
- in the verifier, a FAIL whose `verification.md` lists the blocker.

The next attempt's prompt after a `restore failed` carries the guard note with the new `_ADVICE` entries (a planted link
halts, so its entry only serves a guard note that is built before the halt):

- `"planted link"`: "A test run replaced a directory or file of the worktree with a symbolic link. The harness never
  writes through one: it removed the link and discarded the attempt. Create links only under the test's own temporary
  directory (`tmp_path`)."
- `"restore failed"`: "The harness could not put a file back after a test run changed it. Tests must not replace,
  delete or lock source files."
- `"link outside worktree"` (D11): "A symbolic link that points outside the repository (an absolute target, or `..`
  above the root) is never committed: the harness discarded the step. Keep the link out of the work, or point it at a
  path inside the repository."

## D5. `restore_to_base` and the production guard

`restore_to_base(wb, base, path)` loses its `existed` argument. Its five callers are updated:

- `enforce_red_scope`, three calls;
- `ProductionGuard.check`;
- `tdd.py:939`.

The new body:

1. While `linked_component(root, path)` is not None, call `remove_link` on it. A link the agent or a gate put there is
   never followed. A link at the path itself is removed too; when the base had a link there, the checkout below puts
   it back.
2. Ask git for the kind at the base with `git cat-file -t <base>:<path>` (`check=False`).
3. If the kind is `blob`, `tree` or `commit`, run `git checkout <base> -- :(literal)<path>`. For a former directory
   this restores the whole tree: git removes a non-directory in the way and does not follow it [V].
4. If the path is absent at the base, remove what is there: `unlink_inside` for a file, or `shutil.rmtree` for a
   directory, which is safe because step 1 removed every link above it. Then run `git rm --quiet --cached
   --ignore-unmatch -r -- :(literal)<path>`, the `_put_back` pattern.

`enforce_red_scope:740` writes the rebuilt file with `write_inside`. An `UnsafeFile` (a `LinkedPath` included) from
that write is handled as the existing `except (ValueError, UnicodeDecodeError, OSError)` branch above it handles an
unreadable file: `restore_to_base` and a `red scope` violation with the note `the file is not readable Python source`.
These are agent-step links, not gate links, so nothing goes to `wb.unsafe`.

`ProductionGuard`:

- `_read` uses `read_inside`, so a linked path reads as None.
- `check(where)` first collects, for every path in `now ∪ guarded`, its `linked_component`. A link found there was put
  by the gate: red scope left no link among the guarded paths, because `_read` refuses links. `check` passes each
  distinct link to `wb.refused_write(LinkedPath(link), path=…, where=where)`, which records it and removes it.
- The existing loop then runs. A former directory is checked out whole by `restore_to_base`. A guarded file is
  written with `write_inside` (the `unlink`, `rmtree` and `mkdir` lines go), and a directory in its place is removed
  first with `shutil.rmtree`.
- The notes and `gate-mutated-production` violations stay as they are. The `planted link` record also fails the
  attempt through `tampered()`.

## D6. What counts as gate and runner configuration

The constants live in `src/l4/implementer/gateconfig.py`. A *whole file* is guarded by its bytes. A *section* is
guarded by its parsed value: `tomllib` for `pyproject.toml` and any `*.toml`; `configparser.RawConfigParser(strict=
False, interpolation=None)` for `setup.cfg` and `tox.ini`; `json` for `package.json`. A comment or whitespace edit is
therefore no change. A file that parses at one end and not at the other counts as changed in every guarded section.
A file that parses at neither end is compared by its bytes. All globs match at any depth (`g` or `**/g`, as `_exempt`
does), so `packages/api/ruff.toml` counts.

| Kind | Whole files | Sections of manifests | Script entries (D6.1) |
|---|---|---|---|
| gate | `tdd.gate_config_globs` + `tdd.extra_gate_config_globs` | `pyproject.toml`: `tool.mypy*`, `tool.ruff*`, `tool.pylint*`, `tool.pyright*`, `tool.basedpyright*`, `tool.black*`, `tool.isort*`, `tool.flake8*`, `tool.bandit*`, `tool.pydocstyle*`, `tool.codespell*`. `setup.cfg`, `tox.ini`: `mypy`, `mypy-*`, `flake8`, `pylint*`, `isort`, `pycodestyle`, `pydocstyle`, `bandit`. `package.json`: `eslintConfig`, `eslintIgnore`, `prettier`, `stylelint` | resolved from `gates.build`, `gates.lint`, `gates.typecheck` and `gates.extra[*].command` |
| runner | `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `.coveragerc`, and each `tdd.runner_config_files` entry that is not `pyproject.toml`, `setup.cfg`, `tox.ini` or `package.json` (`jest.config.*`, `vitest.config.*`, `playwright.config.*`, `karma.conf.*`, `.mocharc.*`) | `pyproject.toml`: `tool.pytest*`, `tool.coverage*`. `setup.cfg`: `tool:pytest`, `coverage:*`. `tox.ini`: `pytest`, `coverage:*`. `package.json`: `jest`, `mocha`, `nyc`, `c8`, `ava`, `scripts.test` | resolved from `gates.test.command` and `gates.e2e.command` |
| free | lock files (`stubs.LOCKFILES`) and every other file | every other section: `project`, `dependency-groups`, `build-system`, `tool.uv`, `tool.poetry`, `dependencies`, `devDependencies`, `scripts` entries no gate command runs, `tool.poe` when no gate command runs `poe`, and the rest | — |

**The `markers` exception (owner decision 5).** `pytest.ini`, `.pytest.ini`, `pytest.toml` and `.pytest.toml` are not
compared as bytes: they are parsed (INI, TOML) section by section, so that the pytest settings can be compared the way
the manifests' are. For a pytest section (`[pytest]`, `[tool:pytest]`, `tool.pytest` with its `ini_options`) the view
of the step base and the view after are the same when every key but `markers` is equal and the base's `markers`
entries, taken as a set, are all still there (an INI `markers` value is one entry per line, a TOML value a list). So
adding an entry is no change; removing one, changing one (it is a removal and an addition) or touching any other key
(`asyncio_mode`, `addopts`, plugins) is. The same comparison serves the guard (D7), the post-gate restore, the
verifier's step 1 (D9) and the red-to-green freeze of `check_freeze`, which now asks `GateConfig.changed` for the
`runner` kind instead of comparing whole `[tool.pytest*]` tables, so that a marker green registered is not a blocker one
round later.

New defaults for `tdd.gate_config_globs`: `pyrightconfig.json`, `pylintrc`, `.eslintignore`, `.prettierrc*`,
`.prettierignore`, `biome.json`, `biome.jsonc`. New default for `tdd.runner_config_files`: `.coveragerc`. The new key
`tdd.extra_gate_config_globs` (default `[]`) is appended, as `extra_test_globs` is (L4-CFG-001). A repository whose
config sets `gate_config_globs` keeps its own list. A name in both lists counts as runner configuration.

Public API of the module, one object built per step or per gate run:

```python
Kind = Literal["gate", "runner"]

@dataclass(frozen=True)
class GateConfig:
    globs: tuple[tuple[str, Kind], ...]   # whole-file globs and their kind (a runner glob wins over a gate glob)
    scripts: dict[str, Kind]              # D6.1: a script path, or a `package.json` key such as "scripts.lint"

    @classmethod
    def of(cls, cfg: L4Config, root: Path) -> "GateConfig": ...
    def kinds(self, path: str) -> frozenset[Kind]
        # empty: the path is no configuration; a manifest can hold both kinds
    def view(self, path: str, data: bytes | None) -> dict[str, tuple[Kind, object]]
        # section name ("" for a whole file) -> (kind, parsed value or bytes); only guarded sections; None -> {}
    def changed(self, path: str, before: bytes | None, after: bytes | None) -> dict[Kind, tuple[str, ...]]
        # per kind, the guarded section names whose views differ, sorted; ("",) is the whole file
```

### D6.1 Script entries a gate command resolves to

`GateConfig.of` fills `scripts` with a deliberately bounded resolver. For each configured command it applies these
rules:

1. Run `shlex.split`. The command `sh -c '<text>'` (or `bash -c`) is split once more. The tokens are cut at `&&`,
   `||`, `;` and `|` into simple commands.
2. Each simple command drops leading `VAR=value` tokens, `env`, `uv run`, `poetry run`, `npx`, `pnpm exec` and a
   `.venv/bin/` prefix.
3. The command head is then resolved:

| Head | Resolves to |
|---|---|
| a relative path to a file in the worktree, or the first argument of `sh`, `bash`, `python`, `python3` or `node` that is one | that file |
| `make` | `Makefile`, `makefile`, `GNUmakefile` |
| `just` | `justfile`, `Justfile`, `.justfile` |
| `tox` | `tox.ini` as a whole file |
| `poe` | `pyproject.toml` section `tool.poe` |
| `npm run X`, `npm X` for `test`/`start`, `pnpm [run] X`, `yarn [run] X` | `package.json` keys `scripts.X`, `scripts.preX`, `scripts.postX` |

The kind is `runner` for the test and e2e commands and `gate` for the rest. Anything else resolves to nothing [I: this
covers the gate commands of the consumer repositories seen so far; a richer runner is an open question].

## D7. The guard: when it runs and what it does

`gateconfig.revert_gate_config(wb, task, base, *, phase, opened) -> list[ConfigChange]` runs in `tdd.agent_step`'s
`finally`, right after `revert_protected` and before `restore_ledger`. That covers red, green and single (fix
chores), on every exit path of the agent step. `ConfigChange(path, kind, sections, action)` is a frozen dataclass.

1. Candidates: the paths of `changed_paths(wb.git, base, excludes=wb.excludes)` whose `GateConfig.of(wb.cfg,
   wb.worktree).kinds(path)` is not empty.
2. For each candidate, `before` is `git show <base>:<path>` (None when absent). `after` is
   `read_inside(worktree, path, limit=4 MiB)`, and a `LinkedPath` or `UnsafeFile` counts as a change of every section.
   `changed(path, before, after)` gives the changed sections per kind, filtered to the kinds that D8 does not allow.
3. If any section is left, the whole file goes back to the step base with `restore_to_base(wb, base, path)`; a file
   that is new is removed. The guard emits `guard.violation{phase, rule: "gate configuration" | "runner
   configuration", path, sections: [...], why: "changed <sections>", action: "restored" | "removed", task, attempt}`.
   When a file holds both kinds, there is one event per kind.

Why the whole file goes back:

- TOML has no writer that keeps the file's layout in the standard library (NFR-004 keeps dependencies small).
- Splicing `[tool.x]` text regions out of a file is fragile: dotted keys, inline tables, a `[tool]` table.

The cost is that a legitimate dependency change in the same file and step is undone. The guard note says to write it
again without the gate sections. The new `_ADVICE` entries:

- `"gate configuration"`: "Lint, type-check and other gate settings (ruff, mypy, eslint, tsconfig, and the gate
  sections of pyproject.toml, setup.cfg, tox.ini and package.json) are the project's: the harness put the whole file
  back to the step's base. Make the code meet them. A dependency you added in the same file must be written again
  without touching those sections. If a setting is wrong, ask a question that names the file."
- `"runner configuration"`: "Test-runner settings (the pytest and coverage sections, addopts and plugins, jest and the
  like) are not the step's to change: the harness put the whole file back to the step's base. Write the change again
  without them. If the task needs one, ask a question that names the file."

`_exempt` (`stubs.py:678`) is unchanged. Red may still change the dependency sections of `pyproject.toml`,
`package.json` and the rest, and the lock files. Their guarded sections are handled by the guard above, which has
already run when `enforce_red_scope` starts.

**After every gate run.** `Workbench.run_gate_spec` takes a snapshot before the gate. The snapshot holds every
tracked path (`git ls-files -z`) and every untracked path that HEAD's ignore rules do not hide
(`untracked_files(git, HEAD, excludes)`) whose `kinds` is not empty. Each such path maps to the
`(bytes, mode)` that `read_inside` gives, or to None. In the existing `finally`, after the protected-path restore, the
listing is taken again together with the snapshot's keys. Every path whose `changed` against the snapshot is not empty
is handled:

- a snapshot entry with content is put back with `write_inside`;
- a new file is removed with `unlink_inside`;
- an `UnsafeFile` from either goes to `refused_write` (D4), so nothing raises out of the `finally`;
- the guard emits `guard.violation{phase: "gate", rule: <kind> + " configuration", path, sections, action, where:
  <gate name>}`.

No tag lifts this: no gate has a reason to edit configuration. It applies to the verifier's gates too. It does not by
itself fail the attempt, the way a protected path that a gate changed does not. The following gates run on the
configuration as it was, and the change never reaches a commit.

## D8. Allowing a change: a tag or a person's answer

| Phase | Gate configuration is allowed when | Runner configuration is allowed when |
|---|---|---|
| red | `[config]` or `[test-infra]` in the task title, or opened by an answer | `[test-infra]`, or opened by an answer |
| green | `[config]` or `[test-infra]`, or opened by an answer | never: the red-to-green freeze of L4-IMP-002 |
| single | `[config]` or `[test-infra]`, or opened by an answer | `[test-infra]`, or opened by an answer |

- Tags are read with `verifier.scan.task_tags(task.title)`, which already serves `[test-infra]` in
  `freeze_test_paths`. The check does not depend on how a `tdd.exempt_task_kinds` exemption runs (implementer-tdd-loop
  1.25 is M1).
- Red scope still decides what red may change. A gate file such as `mypy.ini` is a non-Python production file there,
  so a `[config]` task makes that change in green. The tag lifts this guard, not red scope.
- A person's answer: `unfreeze.config_opened(questions, events, scope, candidates, *, phase) -> Unfreeze` has the
  rules of `unfrozen` (L4-IMP-015):
  - the Status is `answered` or `accepted` by a human, never `answered-by-clarifier`;
  - the ledger holds a `question.answered{by: human}` with the digest of the text as it is now;
  - the kind is not `verdict`, and the question blocks the task or an ancestor;
  - the answer names the path (`names_path`), and an `accepted` suggestion must be named by the question too;
  - at most `MAX_PATHS_PER_QUESTION` paths open.
- `candidates` are the configuration paths at the step base. In green, a path that holds only runner configuration
  goes to `kept` with the why `the runner sections are frozen from red to green (L4-IMP-002)`. A manifest opens for
  its gate sections only.
- `agent_step` computes the grant before the agent runs. When anything opened, it emits
  `task.config_opened{task, phase, paths, question, answer_sha256, kept}`. The answer already reaches the prompt as
  answers do (`<l4:data>`), so no template changes and the template lock is not touched.

## D9. The verifier checks the same rule on the commits

A new sub-check `("gate configuration", check_gate_config)` joins `integrity.CHECKS` after `content scan`. It looks at
every path that differs between base and head and is configuration (D6, with `gc = GateConfig.of(ctx.cfg,
ctx.git.repo)`). For each path, `_introducers(ctx, path, lambda b, a: bool(gc.changed(path, b, a)))` finds the commits that changed a guarded
section. Each commit is then judged:

| Commit | Result |
|---|---|
| only people's commits (`_by_people`) | listed in `human_config` |
| a harness commit whose `L4-Task` (unit, task) carries `[config]`/`[test-infra]` (gate) or `[test-infra]` and `L4-TDD` is not `green` (runner) | allowed |
| a harness commit that a `task.config_opened` of that unit and task names for the path, with the same phase rule | allowed |
| any other harness commit | blocker: `gate or runner configuration changed by the unit` with `<path> (<sections>), commit <sha10>` |

`Outcome.human_config` (`integrity.py`) and `IntegrityReport.human_config` (`types.py`) are filled in `run_integrity` and read back in
`evidence.py`. `report.py` writes them under `## Gate and runner configuration changed by humans (allowed, listed:
L4-IMP-040)`. `check_freeze` stays as it is. The new check covers base→red for runner sections, because a red commit
that changed them without `[test-infra]` or an answer is a harness commit the rule refuses.

## D10. The masked agent folders are protected paths

- `.hermes/**`, `.kiro/hooks/**`, `.kiro/prompts/**` and `.kiro/skills/**` are added to `CONTRACT_PROTECTED_GLOBS`. They
  sit beside `.kiro/agents/**` and `.kiro/settings/**`, and the comment names `GUIDANCE_DIRS`.
- `.kiro/skills` is added to `GUIDANCE_DIRS` (owner decision 4: it is a Kiro guidance root, and `l4 skills install
  --project` writes `.kiro/skills/l4`) and to `m0_guidance` of `scripts/runner/sandbox-probe.sh`, so the sandbox masks it
  and the drift test covers it. A person installs the skill (`l4 skills install`, outside any step), so a step has no use
  for the folder. The existing `test_bwrap_argv` test of the Kiro folders lists `skills` too.
- `anchored_roots()` derives the gate snapshot roots from the globs, so the gate guards cover the new paths with no
  other change [V, read: `protected.py:92-97`].
- A drift test asserts `ProtectedSet().match(f"{d}/x") is not None` for every `d` of `GUIDANCE_DIRS`. It also asserts
  that `m0_guidance` of `scripts/runner/sandbox-probe.sh` lists the same directories. The existing `test_probe_parity`
  pattern is in `tests/unit/sandbox/`.
- The generic guard note `_GENERIC` already names "agent configuration".
- In SPEC, L4-SEC-002's guidance list gains the four paths, and L4-SEC-005's list of masked folders `.kiro/skills`, so
  that L4-SEC-002, L4-SEC-004 and L4-SEC-005 agree.

## D11. No step commits a link that points outside the worktree (owner decision 3)

`stubs.escaping_links(wb, base) -> list[tuple[str, str]]` lists, for every path of `changed_paths(git, base)` that is a
symbolic link now (`lstat`), the `(path, target)` pairs where the target is absolute, or climbs above the root once it is
joined to the link's directory and normalized. A link that `base` holds at that path with the same target (`git ls-tree`
mode `120000`, blob text) is left out. `tdd.outside_links_reason(wb, base, phase)` emits one `guard.violation{phase,
rule: "link outside worktree", path, action: "refused", target, why}` per link and returns the reason `the step left a
symbolic link that points outside the worktree: <path> -> <target>[, …] … nothing of this attempt is kept` (at most 5
links, then `(+N more)`). It runs once per attempt, after every gate and before the commit:

| Step | Site |
|---|---|
| red | before the red commit and before the already-satisfied commit, after `tampered(...)`: `wb.discard_changes()` and a failed `RedOutcome` |
| green | `reason = stop_on_unsafe(wb) or reason or outside_links_reason(wb, base, "green")` |
| single | the same line with `"single"` |

It is not inside `Workbench.commit`, because it has to produce a failed outcome, not an exception. A refusal is an
attempt failure, not a halt: the link is the step's own, and the next prompt carries the guard note (D4). A link that
stays inside the worktree is not refused, and neither is a link a gate planted at a production path that stays inside
(the restores of L4-SEC-020 refuse to write through it, D1). `Step.links` of the fake adapter is the test lever.

## Residual risks

- Under `NoSandbox` (macOS, local development only, L4-NFR-005) the gate itself can still write anywhere. This change
  protects the harness's own writes, not the gate's.
- A link that stays inside the worktree and that a step or a gate puts in place of a production directory is not
  refused in green and in a fix chore, which have no production guard. The harness never writes through it (D1), and
  a link that leaves the worktree is refused before every commit (D11).
- The script resolver (D6.1) sees only the listed command shapes. A gate that runs a script through another tool, for
  example `nox`, `invoke`, `bazel` or a wrapper binary, is not resolved, and its script is free.
- The whole-file revert can cost an attempt when a step mixes a dependency change with a gate-section change.

## Rejected alternatives

- Repair-and-continue for a planted link, without failing the attempt: a test that ran `rm -rf src/pytdd` would pass
  once the harness healed the tree.
- Failing one attempt for a planted link and halting only after `max_task_attempts`: the owner chose to halt at once
  (decision 1), because code that plants links is evidence for a person, not a mistake to retry.
- Raising `LinkedPath` out of the `finally` and catching it in `run_task`: a `finally` that raises replaces the
  exception in flight, and today's `RuntimeError` there already has no catcher.
- Section-level splicing of TOML (see D7).
- Comparing the resolved parent before and after the gate, the reviewer's first option: weaker than the descriptor walk
  (D1).
- A full-tree link sweep after every gate: false positives (bazel's convenience links, `node_modules/.pnpm`) and no
  gain over the walk on the paths the harness actually writes.

## Owner decisions (answers to the open questions of the first draft)

1. **A planted link halts the unit at once**, like `secret_in_push` (D4: `PlantedLink`, `breaker.tripped{reason:
   planted_link}`, halt code `planted_link`). Applied with group 4. `restore failed` was not named by the decision and
   stays an attempt failure; it is the one reading made by the implementation, and the verifier keeps the blocker.
2. Putting the whole configuration file back is accepted (D7). The retry note says which file went back and why, and
   that a dependency change in the same file must be made again without the configuration change (D7 advice,
   SCN-IMP-258). Applied with group 7.
3. **Every phase refuses to commit a link that points outside the worktree** unless the base holds the same link (D11,
   L4-SEC-020 part e). Applied with group 4.
4. `.kiro/skills/**` is masked in the sandbox and protected, like the other guidance folders; the drift test covers it
   (D10). Applied with group 5.
5. The defaults stand (the seven gate globs, `.coveragerc` as runner configuration), with ONE narrow exception: a red
   or green step may add entries to pytest's `markers` list without a tag or an answer (D6, SCN-IMP-254..257).
   Applied with groups 6, 7 and 9.
