| line | change task | status | commit | note |
|---|---|---|---|---|
| S0 | seams: versions, testwriter | done | cdaebae + m1.x(fix) | review fixes: per-kind prompt, WriterReply.run, label sanitising, MemoryError, write_test_file overwrite/.git guard, tests |

Merger requests (S0 keeps to new files only, so parallel-ownership.md is untouched on this branch; apply these to §3.0 on main after S0 lands):

- `WriterReply` gains `run: RunResult | None = None` (the agent run behind a limit/timeout/error; RoleLimit and Factory.on_limit need it).
- `write_test_file(worktree, rel_path, code, *, overwrite: bool = False)`: an existing file raises FileExistsError by default, so L4-VER-002a holds by construction; an in-round retry rewriting its own file passes `overwrite=True`. Refuses `..`, absolute paths, symlinked parents and `.git` (case-insensitive).
- `test_path` raises ValueError for an unknown kind or a `round_no` that is not an int >= 1; `request_test` raises ValueError for a malformed criterion id before any LLM call.
- The system prompt is a shared preamble plus a per-kind rules block; data-block labels are sanitised and appear only in `source=`, under fixed `## Source N` headings.
- M1.3 / M1.5 callers: the first write of a generated test uses the default (no overwrite); only the retry of the same round passes `overwrite=True`.


## Consumer note (orchestrator, 2026-10-04)

`write_test_file(worktree, rel_path, code)` — the plain three-argument call of §3.0 — writes a file whose first line is `GENERATED_MARKER` and **replaces an existing file only when it is the harness's own generated file** (first line = marker), so an in-round retry, a crash-resume of the same round, and a later round regenerating the same `test_path` all work without extra arguments. A file the harness did not generate raises `FileExistsError` (L4-VER-002a). `overwrite=True` forces, `overwrite=False` refuses any existing file. `WriterReply.run` carries the `RunResult` of a limited call (for `RoleLimit` / `Factory.on_limit`).
