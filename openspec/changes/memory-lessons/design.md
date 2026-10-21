## Context

SPEC section 13 and architecture section 11: lessons are plain Markdown under `.serena/memories/` committed to the
target repository; `harness/lessons.md` is written only by the harness; agents may write proposals only to
`inbox/<run-id>/`; lessons are injected through the strongest channel of each adapter and always wrapped in
`<l4:data kind="lessons">`. Defaults (SPEC section 3.2): `memory.enabled: true`, `lessons_file:
.serena/memories/harness/lessons.md`, `max_lessons: 40`, `max_bytes: 12000`, `serena: {enabled: true, version:
"1.7.0", context: auto}`. M1 scope (implementation map): read the lessons file and inject it into prompts as
`<l4:data>`; Serena MCP wiring is M2.

Evidence labels follow SPEC: [V] verified, [I] design decision, [U] unverified - a test or spike must confirm it.

## Goals / Non-Goals

Goals:

- A deterministic, merge-friendly lessons file whose content reaches every prompt as data, with the injected IDs
  visible in the ledger.
- Curation that can only be driven by evidence (verifier finding whose fix passed, repeated guard violation, human
  edit), never by an agent's own claim.
- Serena strictly optional: any Serena failure degrades to prompt-only injection.

Non-Goals:

- Prompt template assembly (`implementer-tdd-loop`), adapter CLI construction (`agent-factory`; this change returns a
  `DeliveryPlan` they apply), the verifier's finding schema (`verifier`), `.gitattributes`/`.serena/project.yml`
  creation by `l4 init` (`forge-and-ci`; this change supplies the content).
- Embedding/vector retrieval of lessons; semantic ranking (selection is glob/kind based).
- Serena 2.0 (GPL, breaking) - pinned to 1.7.0 [V, PyPI + repo, 2026-10-03].

## Decisions

### D1. Modules and key data structures

`l4.memory.lessons`

- `@dataclass(frozen=True) Lesson`: `id`, `title`, `scope_globs: tuple[str, ...]`, `scope_kinds: tuple[str, ...]`,
  `source`, `dedupe_key`, `supersedes: str | None`, `reinforced_count: int` (default 1), `last_reinforced: date |
  None`, `body: str`, `extra_bullets: tuple[tuple[str, str], ...]` (unknown bullets are preserved on round trip).
- `@dataclass LessonsFile`: `header: str` (the `<!-- l4:lessons v1 ... -->` comment), `lessons: list[Lesson]`.
- `EMPTY_TEMPLATE: str` - the header comment only (what `l4 init` writes).
- `lesson_id(dedupe_key: str) -> str` = `"L-" + sha256(dedupe_key.strip().encode("utf-8")).hexdigest()[:8]`.
- `parse_lessons(text: str) -> ParseResult(file: LessonsFile, problems: list[Problem])`: LF or CRLF input; sections
  start at `## L-<8 hex> · <title>`; the bullets `**Scope:**`, `**Source:**`, `**Dedupe key:**`, `**Supersedes:**`,
  `**Reinforced:**` are read; the first non-bullet block is the body. A malformed section is reported and skipped; a
  header with a version other than `v1` makes `parse_lessons` return no lessons and a `Problem` (fail safe: unknown
  format is never injected).
- `render_lessons(file) -> str`: canonical, LF, lessons sorted by ID, bullets in a fixed order, one blank line between
  sections, written with temp file + `os.replace` (Serena 1.7.0 writes non-atomically [V, research/05]).
- `lint(file, max_lessons, max_bytes) -> list[Problem]`: unique IDs, `id == lesson_id(dedupe_key)`, `supersedes`
  points to an existing or archived ID, valid scope globs, caps (doctor MEM-001).
- `glob_match(pattern, path) -> bool`: POSIX path glob with `**` spanning directories, imported from sandbox-security's
  `l4.security.protected.glob_match` (Python 3.11 has no `PurePath.full_match`; one translator for the whole harness).
- `select_lessons(file, task_paths: Sequence[str], task_kinds: Sequence[str]) -> list[Lesson]`: a lesson matches if
  (no globs or any task path matches a glob) and (no kinds or a kind intersects `task_kinds`); lessons superseded by
  another selected lesson are dropped; order = ID order.

`l4.memory.inject`

- `build_lessons_block(lessons) -> str`:
  `<l4:data kind="lessons" ids="L-a,L-b">` then each lesson as `### <id> <title>` + body, then `</l4:data>`; the text
  of lessons is escaped so that no `<l4:` or `</l4:` sequence survives (`&lt;l4:`), and then passed through the
  redaction filter (L4-OBS-002).
- `@dataclass Injection`: `block: str`, `ids: tuple[str, ...]`, `skipped: tuple[Problem, ...]`.
- `inject_for_task(worktree: Path, cfg: l4.config.schema.MemoryCfg, task_paths, task_kinds, writer: LedgerWriter | None) ->
  Injection`: reads `cfg.lessons_file` from the worktree (the branch's file = base lessons plus own-branch lessons),
  returns an empty `Injection` when memory is disabled, the file is absent or empty, or no lesson matches; appends one
  `lessons.injected{ids, channel, bytes}` ledger event when a writer is given.
- `PROTECTED_MEMORY_PATHS = (".serena/memories/harness/**",)` for the implementer guard (L4-IMP-006).

`l4.memory.channels` (M2)

- `Channel = prompt_section | claude_append_system_prompt | kiro_resources`; `plan_delivery(adapter: str, injection,
  workdir) -> DeliveryPlan(channel, extra_argv: list[str], files: dict[Path, str], prompt_section: str | None)`.
  Claude: `--append-system-prompt <block>` [V flag name, research/02]; Kiro: a `resources` entry pointing to a file
  holding the block in the harness-generated agent config [U exact resource syntax, settled by the agent-factory Kiro
  contract test]; every other adapter: the prompt's lessons section. The block is identical on every channel.

`l4.memory.curate` / `l4.memory.inbox` / `l4.memory.commit` (M2)

- `Origin = verifier_finding_fixed | guard_violation_repeated | human_edit | agent_proposal`.
- `LessonCandidate`: `dedupe_key`, `title`, `scope_globs`, `scope_kinds`, `source`, `body`, `origin`, `supersedes`.
- `curate(file, candidate, cfg, today) -> CurationResult(file, action, archived)` with `action` in
  `created | reinforced | quarantined | rejected`: an `agent_proposal` is never `created` (it is written by
  `inbox.store_proposals` and only `promote` or a matching dedupe key can lift it); an existing dedupe key reinforces
  (count + 1, date today); caps are enforced after insertion by moving the least recently reinforced lessons to
  `.serena/memories/harness/_archive/<id>.md` until `max_lessons` and `max_bytes` hold.
- `guard_violation_repeated(events, kind, min_runs=2) -> bool` [I: two distinct runs].
- `inbox.store_proposals(worktree, run_id, proposals) -> list[Path]` writes `.serena/memories/inbox/<run-id>/<n>.md`.
- `commit.commit_memory_change(git, worktree, run_ctx, message_detail)` makes a separate commit
  `chore(memory): <detail>` with trailer `L4-Phase: lessons` through the hardened `Git.commit` of `state-vcs-locks`.
- `l4 lessons promote ID` (human) moves an inbox proposal into `lessons.md` as a `human_edit`-origin lesson.

`l4.memory.serena` (M2)

- configuration from bootstrap-core's `l4.config.schema.SerenaCfg` (`enabled`, `version="1.7.0"`, `context`; no second model here); `serena_argv(binary, context, project) -> list[str]` =
  `[binary, "start-mcp-server", "--context", <claude-code|codex|ide>, "--project", <worktree>,
  "--enable-web-dashboard", "false", "--open-web-dashboard", "false", "--mode", "one-shot", "--mode",
  "no-onboarding"]` [V-run, research/05]; `serena_env(job_dir) -> {"SERENA_HOME": ..., "CI": "true"}` and a
  generated `serena_config.yml` with `base_modes: [editing]` (default `[interactive, editing]` would invite questions
  nobody answers) [V-run].
- `render_project_yml(existing) -> str` merges `read_only_memory_patterns: ["(?!inbox/).*"]`,
  `ignored_memory_patterns` for `_archive/`, and `initial_prompt: "{{ embed_memory('harness/lessons') }}"` [V-run]
  without touching other keys.
- `mcp_timeouts(adapter) -> McpTimeouts` (OpenCode >= 20 s, Codex `startup_timeout_sec = 30`) [SPEC L4-MEM-004].
- `check_serena(argv, env, timeout) -> SerenaStatus(ok, reason)`: never raises; any failure yields `ok=False` and one
  warning. `serena_enabled_for_run(...)` returns false when the check failed; Kiro argv builders must not add
  `--require-mcp-startup` for Serena (`kiro_require_mcp_startup(servers)` filters it out).

### D2. Lesson IDs are a pure function of the dedupe key [SPEC MEM-002a]

`L-<first 8 hex of sha256(dedupe key)>`. The SPEC's example (`L-3f9a1c2e` for `e2e-selector-brittle`) is illustrative
and not the real hash: sha256 of the key as UTF-8 gives `L-ea1ceace` [V-local, computed 2026-10-03]. Hashed bytes
are the key stripped of surrounding whitespace, nothing else (no case folding), so the same key on two branches
yields the same ID. Alternative: random IDs (rejected: parallel branches creating the same lesson would not merge).
A 32-bit prefix collides in a file of at most 40 lessons with probability below 1e-6; lint reports a collision.

### D3. Merge-friendly file layout [V-local spike]

Spike (git 2.48.1, 2026-10-03): lessons sorted by ID, two branches each inserting one lesson. Far-apart insertions
merge cleanly with the default merge driver; two insertions between the same neighbours produce a conflict; with
`merge=union` in `.gitattributes` both cases merge cleanly. Decision: the writer always emits ID order, and `l4 init`
(change `forge-and-ci`) adds `.serena/memories/harness/lessons.md merge=union` next to the SPEC's `text eol=lf` entry
(an amendment to L4-INS-002, tracked in the definition-of-done tasks). The union driver can duplicate a section that
was *edited* (reinforced) on both sides; lint reports duplicate IDs and `curate` repairs them by keeping the highest
`reinforced_count`.

### D4. Injection is data, escaped, and never skipped silently

Lessons are written by the harness from evidence, but a human edit or a verifier finding body can contain arbitrary
text. The block therefore escapes `<l4:` / `</l4:` so a lesson cannot close the data block or open another one, then
redaction runs. A parse problem in one lesson skips only that lesson and logs a warning; an unknown file version
injects nothing and logs a warning. Alternative: refuse the run on lint errors (rejected: lessons must never block
delivery).

### D5. Channel per adapter (M2)

The M1 channel is always the prompt's lessons section (`implementer-tdd-loop` renders `Injection.block` there). M2
adds the strongest channel per adapter. The block text is identical on every channel so the ledger `ids` are
channel-independent; the `channel` field records which was used.

### D6. Curation only from evidence [SPEC MEM-002]

`Origin.agent_proposal` can never create a lesson by itself; the exception in SPEC (matches an existing dedupe key) is
a reinforcement of an existing lesson, not a creation. The implementer's own claims are not an `Origin`.

### D7. Serena is advisory

Serena failures (missing binary, cold start beyond the MCP timeout, port or config clobber) must never fail a run.
The prompt injection path has no dependency on Serena. A per-job `SERENA_HOME` avoids the config clobber seen with
parallel agents in <= 1.7.0 [V, research/05].

## Risks / Trade-offs

- [U] Kiro agent `resources` syntax for a file outside the workspace: confirm by the agent-factory Kiro contract test.
- [U] Claude `--append-system-prompt` size limits for 12 KB blocks: contract test with the largest allowed file.
- Merge-friendliness depends on `merge=union` (D3); without it, parallel lessons may conflict (human resolves; lint
  keeps the file valid).
- A lesson whose body is stale keeps being injected until superseded or archived; mitigated by `last_reinforced`
  ordering and the cap.
- Task kinds (`ui`, ...) need a source: SPEC names kinds in `Scope` but does not say how a task gets one. M1 passes an
  empty kind list (kind-scoped lessons are not selected); M2 reads kinds from task tags (see Open points).
- Injecting 40 lessons / 12 KB into every prompt competes with `implementer.context_budget_tokens`; selection by scope
  is the mitigation, and `Injection.bytes` is logged.

## Open points (SPEC ambiguities resolved here)

- The SPEC example lesson ID is not the sha256 of its dedupe key (D2); the rule, not the example, is normative. Amend
  the SPEC example in this change.
- Reinforcement count/date (SCN-MEM-04, "least recently reinforced") has no field in the L4-MEM-001 format; an optional
  `- **Reinforced:** <count> · <YYYY-MM-DD>` bullet is added. Absent means count 1 and the date in `Source`.
- Where overflow lessons go is only "`_archive/`"; chosen: `.serena/memories/harness/_archive/<id>.md`.
- How a task gets "kinds" is unspecified; assumed to be a task tag like `[ui]` provided by spec-providers (M2).
- "A guard violation repeated across runs" has no threshold; chosen: the same `guard.violation` kind in at least two
  distinct runs of the same repository.
- The `.gitattributes` `merge=union` entry (D3) extends L4-INS-002's file list.
