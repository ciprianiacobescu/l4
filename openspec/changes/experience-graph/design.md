## Context

The facts below were read in the code at harness 0.3.0 (`e63a9b02`). Paths are relative to `src/l4/`. The source proposal
is `docs/plan/proposal-experience-graph.md` (main checkout, not committed). Its review of 2026-10-14 is summarised in
`proposal.md`.

- **Ledgers.** One file per run: `<unit_dir>/.l4/ledger/<run-id>.jsonl` (`state/ledger.py:54-61`). A fix unit
  `<parent>-fix-<n>` writes into its parent's ledger (`verifier/fixloop.py:3`). The hand-off commit holds the run's
  ledger (`archive.py:354`). Pending ledgers wait in the lock ref `refs/l4/locks/<fw>/<name>` (`state/pending.py:65`).
  The archive folds them into the folder before it moves (`postmerge.py:136`, `postmerge.py:294`).
- **Reading from git, not the work tree.** `l4 status` reads a unit branch with `vcs/tree.py:regular_blobs` and
  `git cat-file` (`state/status.py:128-145`). It reads an archived change at the base ref (`state/status.py:281`).
  `state/followups.py:83 archive_folders` lists `changes/archive/<date>-<name>` (the newest per name).
  `state/status.py:discover` lists an archived change only when it has a `feedback.md`.
  `specs/openspec.py:180 list_units` skips `archive/`. Kiro units stay in `.kiro/specs/<name>`, and Kiro has no
  archive (`specs/kiro.py:473`).
- **Restarts.** `l4 restart` keeps the old head as `refs/l4/attempts/<fw>/<name>/<n>` and writes
  `unit.restarted{attempt, previous_head, attempt_ref, …}` (`state/restart.py:196`). The new branch has no old `.l4/`.
  CI fetches the unit branches and lock refs (`vcs/refresh.py:34-45`), but not the attempts refs.
- **Verdicts.** `<unit_dir>/.l4/evidence/round-N/verdict.json` (`verifier/report.py:301`) has `round`, `verdict`,
  `base_sha`, `head_sha` and `gates[]`. It has `criteria[]` with `id` and `alias`: `capability › Requirement › Scenario`
  for OpenSpec, `Req <n.m>` for Kiro (`specs/criteria.py:96`, `:227`). It has `findings[]` with `id`, `title`,
  `severity`, `source`, `criterion` and `spec_gap`, plus `profiles{judge, implementer}`. The text is redacted, and the
  forge host is scrubbed before the commit.
- **Finding and criterion ids.** `finding_id` = sha256(title, criterion id) (`verifier/types.py:32`). `criterion_id`
  hashes the framework, the container, the requirement and the leaf (`specs/criteria.py:35`). The container is the
  capability folder for OpenSpec and the unit folder for Kiro (`:97`, `:228`).
- **Implementer events.**
  - `prompt.rendered{role, task, lessons}` (`implementer/tdd.py:568`).
  - `lessons.injected{ids, channel, bytes}` just before it (`memory/inject.py:105`).
  - `task.attempt_failed{task, phase, attempt, reason}` (`implementer/loop.py:233`).
  - `gate.finished{name, status, …}` (`implementer/workbench.py:275`).
  - `availability.selected{role, selected}` (fold: `profiles_used`).
  - `question.raised{id, kind, title, task?}`, `phase.changed{reason, detail}` with the codes of L4-OPS-005, and
    `breaker.tripped`, `guard.*`, `unit.retried`, `unit.restarted`, `verify.verdict{round, verdict}`.
- **Lessons.**
  - `lessons.md` is v1, sections `## L-<8 hex> · title` with `Scope`, `Source`, `Dedupe key`, `Supersedes` and
    `Reinforced` (`memory/lessons.py`).
  - The id is `lesson_id(dedupe key)`.
  - `select_lessons` keeps a scoped lesson only when a task path matches a glob (`:222`).
  - `apply_candidates` writes nothing when `memory.enabled` is false, and refuses a file with parse problems
    (`memory/curate.py:269-277`). `Origin` already has `human_edit` (`:30`).
  - The lessons header says "propose changes via `.serena/memories/inbox/`" (`memory/lessons.py:18`).
- **Who may write `lessons.md`.** On a unit branch, a commit in `base..head` that touches `.serena/memories/harness/`
  and is not the bot's `L4-Phase: lessons` commit is a blocker (`verifier/integrity.py:156-158`,
  `verifier/provenance.py:45`). `base` is the current base head (`verifier/basemerge.py:78`), so a person's commit on
  the base branch is not in that range.
- **Serena.** The inbox is the one place agents may write (`read_only_memory_patterns: ["(?!inbox/).*"]`, L4-MEM-004).
  Agents run in worktrees made from commits, so a file that is not committed never reaches them.
- **Paths and cache.** `l4.config.defaults.cache_root(environ, repo=…)` is `$L4_CACHE`, else `$XDG_CACHE_HOME/l4`,
  else `~/.cache/l4`. It refuses a root inside the repository (L4-CFG-005). `AppContext.out_dir` is `<repo>/.l4-out`,
  which `l4 init` git-ignores.
- **Commands.** Commands are loaded lazily from `commands.py:HANDLERS` (`module:function`). A group command is a
  `"group verb"` key, as `feedback add` is. `tests/unit/test_spec_commands.py` needs one SPEC 2.1 row per handler.
- **Data volume.** `docs/live` holds 32 distinct units, one lesson id, and OpenSpec capabilities that each have one
  unit, except the fix units. The eval seeds are 4 single-task units with memory off.

## Goals / Non-Goals

**Goals:**
- A person can see, from committed records only, what keeps going wrong across the units of one repository, with *n*
  on every number.
- A person can turn a recurring, recorded mistake into a lesson, through the inbox and `l4 lessons promote`, so that
  the existing injection gives it to the implementer.
- A person can see the history of one unit, attempts included, before choosing `l4 retry` or `l4 restart`.
- Nothing changes for a repository where nobody runs these commands.

**Non-Goals:**
- **The automatic loops of the source proposal (L1–L3) are out of scope.**
  - L1 is the dead-scope skip in `select_lessons`. It adds nothing, because selection already needs a matching task
    path. Where it would act (the first file in a new folder), it drops the right lesson.
  - L2 is the graph feeding into `curate`.
  - L3 is `spec-hints` for the clarifier and intake, and a `harness/kg/` view under Serena.
- No prompt change, no gate, no config key, no doctor check, and no change to `l4 run|verify|plan|status|archive|ci *|
  eval`.
- No model call, no network, no forge call, and no fetch.
- No aggregation across repositories.
- No graph database, no embeddings, no lesson text written by a model.

## Decisions

### D1. Manual only, and a hard boundary

- **Commands:** `l4 kg build`, `l4 kg report`, `l4 kg why`, `l4 kg propose` (handlers in `kg/cli.py`), and
  `l4 lessons promote` (`memory/cli.py` → `memory/promote.py`).
- **Import rule.** No module outside `src/l4/kg/` imports `l4.kg`. The only link is the handler string in
  `commands.py`. `memory/promote.py` and `memory/inbox.py` are imported only by `memory/cli.py`. A test checks both
  rules in two ways:
  - **Statically:** an AST scan of `src/l4/**`.
  - **Dynamically:** a subprocess imports `l4.cli`, `l4.orchestrator`, `l4.planner`, `l4.verifier.ladder`,
    `l4.state.status`, `l4.ci.sweeper`, `l4.archive`, `l4.postmerge`, `l4.memory.round`, `l4.implementer.tdd` and
    `l4.eval.run`. It then asserts that no `l4.kg*`, `l4.memory.promote` or `l4.memory.inbox` module is in
    `sys.modules`.
- **No network, no model.**
  - `kg/` does not import `l4.agents`, `l4.llm`, `l4.s1`, `l4.forge`, `l4.sandbox`, `l4.availability`,
    `l4.vcs.refresh` or `l4.vcs.push` (static test).
  - The commands run their git calls through a recording `Git`, which a test restricts to read-only subcommands:
    `rev-parse`, `for-each-ref`, `ls-tree`, `cat-file`, `log`, `diff --name-only`, `check-ignore`, `ls-files`, `var` and
    `config` (read only, to see whether the repository is a partial clone). `promote` may also use `add` and `commit`.
  - **Git never fetches.** The kg `Git` runs with `GIT_NO_LAZY_FETCH=1`, so a partial clone (`--filter=blob:none`)
    cannot fetch a blob that `cat-file` asks for. The unit whose blob is missing is skipped as `partial_clone`, and the
    build warns once.
  - **Indirect imports.** `import l4.kg.cli` and every `l4.kg` module load none of `l4.agents`, `l4.availability`,
    `l4.sandbox`, `l4.forge` or `l4.llm`, even transitively (a subprocess test). The forge-host scrubber is built by
    `l4.config.redaction.attach_forge_urls`, which imports `l4.forge.urls` only when it is called.
  - **The repository root.** A command started in a subdirectory acts on the repository root
    (`git rev-parse --show-toplevel`): the cache-root guard and the `--out` guard (a relative `--out` is relative to the
    `--repo` folder) see the real root, and `ls-tree` runs with `--full-tree`.
  - A test blocks `socket.socket` and still passes every command.
- **Exit codes.** These are the existing codes, with no new one:
  - **0:** done. Skipped inputs are counted and shown, and they are not a failure.
  - **2:** a usage error: an unknown id, no repository, a refused `--out`, a refused promote, a cache root inside the
    repository.
  - **1:** an internal error, with the previous index left intact.
- **Containment.**
  - An exception while reading one unit skips that unit (`skipped{reason: error}`).
  - The commands change no ref, no tracked file, no ledger, and no `.l4/` file.
  - `propose` writes only untracked files under the inbox.
  - `promote` writes only `lessons.md`, its `_archive/` files and one commit.

### D2. Storage: the cache root, per repository, disposable

- **Where:** `cache_root(app.environ, repo=app.repo) / "kg" / <repo key>`. The repo key is the first 16 hex digits of
  sha256 of the resolved repository path. The folder is created with mode 0700. A cache root inside the repository
  is refused with exit 2, as `cache_root` already does.
- **Files:**
  - `nodes.jsonl` and `edges.jsonl`: one JSON object per line, with sorted keys, sorted lines, LF and UTF-8.
  - `manifest.json` (`l4/kg-manifest@1`): the harness version, the read refs as `{ref: sha}` (sorted), the counts by
    node type, `skipped{reason: n}` and `inputs`: the config values that decide what is read
    (`memory.lessons_file`, `forge.base_branch`, `forge.branch_prefix`, `spec.openspec.root`, `spec.kiro.root`) and a
    digest of the forge hosts that are scrubbed.
  - No file holds the build time. The same refs, the same inputs and the same harness version give the same bytes.
    The changed files of a round are decided only from commits that the read refs reach, never from what happens to be
    local.
- **Writes are atomic.** Each file is written with `fsutil.atomic_write_bytes`. `manifest.json` is written last, and it
  holds the sha256 of the other two files. A reader that finds a mismatch, for example after a build stopped halfway,
  treats the index as missing and rebuilds it. A build that fails before its first rename exits 1 and leaves the last
  complete build. An index is never read half-written.
- **Staleness.** `report`, `why` and `propose` read the index. When it is missing, or when a ref in the manifest now
  points elsewhere, or when an input of the manifest now differs, they build it first and say `index rebuilt (refs moved)`
  or `index rebuilt (config changed)`.
- **Disposable.** Deleting the folder loses nothing. There is no second source of truth.
- **Report file.** The default is stdout. `--out PATH` writes the file:
  - a path inside the repository must be git-ignored (`git check-ignore`), and `.l4-out/kg/report.md` is;
  - a tracked or not-ignored path is refused with exit 2;
  - a path outside the repository is allowed.

### D3. Inputs: committed git objects only, never fetched

- **Base ref:** `refs/remotes/origin/<forge.base_branch>`, else `HEAD`, with a warning. The report header shows the
  base sha and its commit date, so a person knows when to `git fetch`.
- **The units come from four places.** Each one is read with `regular_blobs` and `cat-file`, with the existing size
  caps (`MAX_LEDGER_FILE_BYTES` and others), never from the work tree.
  1. **On the base ref:**
     - OpenSpec `changes/<name>/` and every folder `changes/archive/<date>-<name>/`. This is a dedicated walker,
       because `list_units` skips `archive/` and `archive_folders` keeps only the newest per name.
     - Kiro `.kiro/specs/<name>/`.
  2. **The unit branches:** `refs/remotes/origin/<prefix><fw>/<name>` (`for-each-ref`). The unit folder and its
     `<name>-fix-<n>` siblings.
  3. **The lock refs:** `refs/l4/locks/<fw>/<name>`, when local, read with `read_pending_files`. They are merged with
     the branch copy by `merge_ledgers`, as `load_snapshot` does.
  4. **The attempts refs:** the local `refs/l4/attempts/<fw>/<name>/<n>`.
- **A unit seen in several places** is one `unit` node. Each attempts ref adds an `attempt` node, so attempt 1 and
  attempt 2 are not mixed.
- **Files read per folder:**
  - `.l4/ledger/*.jsonl` (`parse_ledger_files`, `LedgerCorrupt` → skipped);
  - `.l4/evidence/round-*/verdict.json` (JSON; a schema other than the verdict schema → skipped);
  - at the base ref, `memory.lessons_file` and its `_archive/*.md` (`parse_lessons`).
- **Skips are counted, never fatal.** Each skip is counted by reason: `ledger_corrupt`, `verdict_unreadable`,
  `oversize`, `not_regular` (a symlink or a submodule), `lessons_problem`, `partial_clone` (git could not read an
  object in a partial clone, and the lazy fetch is off) and `error`.
- **An attempt that is not local.** When a `unit.restarted{attempt_ref}` names a ref that is not local, it is counted
  as `attempt_not_local`. The report prints `git fetch origin 'refs/l4/attempts/*:refs/l4/attempts/*'`, and the
  command never fetches it.
- **Changed files of a round** come from `git diff --name-only base_sha head_sha`, only when both commits are reachable
  from the read refs (`git log <sha> --not <tips>` is empty).
  After a squash merge they often are not. Then the round is counted as `files_unknown`, and nothing is guessed.

### D4. The graph

- **Nodes** (id: type):
  - `openspec:<name>` / `kiro:<name>`: `unit`;
  - `<unit>@<n>`: `attempt` (0 is the current branch);
  - `r-…`: `run`;
  - `<unit>@<n>#round-<k>`: `round`;
  - `F-…`: `finding` (the id as written);
  - `<unit>#<C-…>`: `criterion`;
  - `cap:<name>`: `capability` (OpenSpec: the first part of the alias; Kiro: the unit name);
  - `L-…`: `lesson`;
  - `<unit>#Q-nnn`: `question`;
  - `stop:<code>`: `stop`;
  - `profile:<name>`: `profile`;
  - `failure:<key>`: `failure_class` (D5);
  - `recurrence:<key>`: `recurrence_key` (D5);
  - `gate:<name>`: `gate`;
  - `blame:<value>`: `blame` (D6).
- **Edges.** Each edge has `src` and `ts`. `src` is `<sha10>:<path>#<seq>` for a ledger event, or
  `<sha10>:<path>#/<json pointer>` for `verdict.json`, so that every line of the report can be checked with
  `git show`. The edges are:
  - `HAS_ATTEMPT`, `HAS_RUN`, `HAS_ROUND`, `VERDICT{verdict}`, `RAISED{severity, source, spec_gap}`, `ABOUT`;
  - `IN_CAPABILITY`, `KEYED` (finding → recurrence key);
  - `GATE_FAILED` (round → gate);
  - `INJECTED{task, role}` (run → lesson, from `prompt.rendered{task, lessons}`);
  - `ATTEMPT_FAILED{task, phase, attempt}` (run → failure class);
  - `USED_PROFILE{role}`, `ASKED{kind, answered_by}`;
  - `STOPPED{phase, detail}` (run → stop, from `phase.changed` into `halted`/`escalated`);
  - `RETRIED{reason}`, `RESTARTED{attempt}`, `CLASSIFIED` (→ blame).
- **The lesson-to-finding link does not use the `Source` line,** which holds no finding id (`curate.py:111`). A
  lesson whose dedupe key is a `LESSON_RULES` key is linked to the recurrence key of that rule's `finding_title`. A
  `kg-*` dedupe key (D10) is linked to the key it was proposed from. Any other lesson has no finding link.

### D5. Recurrence by normalised text (approximate)

- **The text normaliser `norm`** applies NFC, then replaces id-like tokens with placeholders:
  - `C-<8 hex>` becomes `<criterion>`, `F-…` becomes `<finding>`, `L-…` becomes `<lesson>`, `Q-<n>` becomes
    `<question>`, and a hex run of 7 or more becomes `<sha>`;
  - a backticked span becomes `` `…` ``, a path with a `/` becomes `<path>`, and a number becomes `#`.

  It then folds case and collapses whitespace.
- **Finding recurrence key:** `norm(title)`, `" | "`, and `norm` of the criterion alias without its capability part
  (`Requirement › Scenario`). For a Kiro finding (alias `Req n.m`), or a finding with no criterion, the second part is
  empty.
- **Failure class** of a `task.attempt_failed.reason`: the first line, cut before the first `:` or ` (`, then `norm`,
  then at most 120 characters. Two examples from live ledgers:
  - `no new test traces C-e25f06d8: tag …` gives `no new test traces <criterion>`;
  - ``lint gate `ruff …` failed (exit code 1):`` gives ``lint gate `…` failed``.
- **Counts are of distinct units** (and rounds or attempts), never of findings ids.
- **Every recurrence line says `approximate`** in the report header: two different mistakes can share a key, and one
  reworded mistake can get two keys.

### D6. Blame from recorded fields only

The first rule that matches wins. The values say who should act; they never say who was at fault.

| Blame | Rule |
|---|---|
| `security` | `guard.secret`; stop `secret_in_push` |
| `spec` | finding `spec_gap: true`; question `kind ∈ {product, ambiguous}`; a NEEDS_HUMAN round with a `spec_gap` finding |
| `environment` | stop `baseline_failed`; `verify.error`; `gate.hung`; `ci.preexisting`; `availability.limit` |
| `verifier` | `judge.reply_repaired`; a finding with `source: human` (a judge finding a person rejected); stop `verifier_errors` |
| `agent` | `guard.violation`, `guard.test_tamper`; `task.attempt_failed`; `feedback.not_addressed`; a deterministic finding without `spec_gap` |
| `unknown` | everything else, a judge finding without `spec_gap` included. It is shown, never guessed |

### D7. Lesson outcomes: what is recorded, as a heuristic

For each lesson (in `lessons.md`, in `_archive/`, or seen only in events):

- **Injections:** the `INJECTED` edges, counted by distinct units, runs and `(run, task, role)`.
- **Followed by attempt failures:** a `task.attempt_failed` of the same run and task with a higher `seq` than the
  injection's `prompt.rendered`, grouped by failure class.
- **Followed by matching findings:** a finding in a later round of the same unit (and attempt) whose recurrence key is
  the lesson's linked key (D4).
- **Status:**
  - `never injected`;
  - `injected, nothing followed`;
  - `injected, followed by <n> failure(s)`.

  Every line carries *n*, and the section header says that this shows what followed the lesson, not what the lesson
  caused.
- **The live case** of job 5528 is what this must show. `L-09421538` was injected into the red prompt of task 1.1, and
  red attempt 1 then failed: the Playwright test was put under `tests/`, and the reason was "new tests fail with an
  error that is neither an assertion nor NotImplementedError". The status is `injected, followed by 1 failure`. The
  source proposal would have called it "holding".

### D8. The report

The report is markdown, in this order. The `--min-units N` option sets the recurrence floor (default 2). Gate
candidates use `max(N, 3)`. All text passes D12's redaction.

1. **Coverage.** The base sha and its date, the units by place (base, archive, branch, attempts), the runs, the
   rounds, the skips by reason, and the attempts that are not local, with the fetch command.
2. **Lessons.** D7, one line per lesson.
3. **Recurring attempt failures.** Failure classes in at least N units: units, attempts, phase (red, green, single,
   fix), and blame.
4. **Recurring findings.** Recurrence keys in at least N units: units, severity, source, and blame.
5. **Gate candidates.** Deterministic findings and failure classes in at least `max(N, 3)` units. A person may write
   a deterministic gate or a lint rule; the report writes nothing.
6. **Spec-gap hotspots.** Per capability: units, `spec`-blame findings, product and ambiguous questions, and
   NEEDS_HUMAN rounds. Kiro capabilities are units, and the header says so.
7. **Profiles by role.** Per `(role, profile)`: the runs that selected it. For implementer profiles also: the tasks
   with a failed attempt, the failed attempts, the mean failed attempts per such task, and the first-round PASS count
   and share (`verdict.json profiles.implementer`). The graph cannot give a first-attempt pass share: a task that
   passes at its first attempt leaves no record, so a task is visible only through an injected prompt or a failed
   attempt. The section says so. Tasks have no kinds yet (memory-lessons design, "Risks"), so there is no breakdown
   by task kind. The eval scorecards stay the authority for comparing models.
8. **Stops.** Per stop code: units, and how each ended (retried, restarted, merged, still stopped).

A line with no data says `none (n = 0)`. Sorting is by count (descending), then by key, so equal inputs give equal
output.

### D9. `l4 kg why ID`

- **A unit id:** a timeline, oldest first. It shows each attempt, with its runs (start, end, exit reason) and its
  rounds (verdict, findings by blame, failed gates). It also shows stops (code and detail), questions (kind, who
  answered), `unit.retried`, `unit.restarted`, `same_failure` and spec edits. Every line ends with its `src`.

  The last line is what the history shows, as facts and not as a command:
  - the number of stops with the same code;
  - whether the unit folder changed since the last stop: `git diff --name-only <stop commit> <branch head> -- <folder>`
    without the `.l4/` files (the stop commit is the last commit that touched the stop's ledger file), or a
    `unit.retried{spec edited}` after the stop;
  - the attempt number.

  The command to run stays the job of `l4 status --unit ID` (`Next:`), which `why` names.
- **`F-…`, `L-…`, `r-…` or `<unit>#Q-nnn`:** the 1-hop neighbourhood, with `src` on each edge.
- **An unknown id** exits 2 with the forms it accepts.

### D10. `l4 kg propose`: drafts for a person, in the inbox

- **Patterns.** It proposes for:
  - (a) a failure class in at least N units;
  - (b) a deterministic finding's recurrence key in at least N units;
  - (c) a guard rule in at least N units. Curation counts guard rules only inside one unit's ledger.

  A pattern is skipped when a lesson with its dedupe key is already in `lessons.md` or `_archive/`, or when a
  `LESSON_RULES` rule covers the finding title.
- **Files.** Each pattern gets `.serena/memories/inbox/kg-<YYYY-MM-DD>/<L-id>.md`:
  - a lessons v1 header and one section;
  - the dedupe key `kg-<a|b|c>-<slug of the key>`, with `L-id = lesson_id(dedupe key)`;
  - the title from a template (`Recurring red failure: <class>`, …);
  - `Source: l4 kg propose <date>: <n> units, <m> attempts`;
  - for a scope, the folders of the changed files of the matching rounds where they are known (as
    `feedback_scope` builds them), else none;
  - a body of one template sentence that states the pattern, then the line
    `TODO(person): write what the implementer should do instead, then run l4 lessons promote <L-id>`.

  A second file, `<L-id>.evidence.md`, lists the units, runs, rounds and `src` pointers. `promote` never reads it.
- **Only harness-owned strings.** A proposal quotes only failure classes (the harness's own reason templates, after
  `norm`), deterministic finding titles in their normalised form (the recurrence key: a title can quote a path an agent
  chose, and `norm` turns it into `<path>`; a `LESSON_RULES` title is the harness's own), gate names, guard rule names
  and globs. A judge finding, a question's text,
  an answer and an agent's output are never quoted. The person writes the advice.
- **It writes nothing else.** It does not stage, commit or touch `lessons.md`. A run on the same day with the same
  index rewrites the same bytes. `--dry-run` prints the files instead of writing them.
- **Ignore warning.** When `git check-ignore` says the inbox folder is not ignored, it warns: `do not commit
  .serena/memories/inbox/kg-*: a committed inbox file is readable and writable by agents through Serena`.

### D11. `l4 lessons promote ID [--from DIR] [--yes] [--no-commit]`

This is L4-MEM-002's human promotion, built for inbox proposals.

1. **Find the proposal.** `ID` is `L-<8 hex>`. The command finds `.serena/memories/inbox/*/<ID>.md`:
   - none found: exit 2;
   - more than one found: exit 2, listing them, unless `--from` names the folder.

   The file must be a regular file under 256 KiB (`reject_symlinks`, `read_regular_file`).
2. **Check it,** and refuse with exit 2 and the reason when any of these is true:
   - `memory.enabled` is false;
   - it does not parse as exactly one v1 section;
   - its heading id is not `lesson_id(dedupe key)` (the message names the expected id);
   - a glob is invalid (`valid_glob`);
   - a `TODO(person)` line is left;
   - the body is empty.
3. **Check the checkout,** and refuse with exit 2 when any of these is true:
   - HEAD is detached, or on a branch under `forge.branch_prefix`. A promote commit on a unit branch is a
     foreign-memory blocker (`integrity.py:156`).
   - Anything is staged.
   - The lessons file in the work tree differs from HEAD (the person's own edit comes first).
   - The current lessons file has parse problems (`apply_candidates` would refuse quietly, so promote says why).
   - `git var GIT_AUTHOR_IDENT` fails.
4. **Show and confirm.** It prints the lesson as it will be written and the paths whose tasks will get it (its scope,
   or `every task`). It asks on a terminal. Without a terminal, `--yes` is needed, else exit 2.
5. **Write.** `apply_candidates(repo, cfg.memory, [candidate with origin human_edit])`. An existing dedupe key
   reinforces it, as L4-MEM-002 says (memory-lessons task 3.7). The caps archive the least recently reinforced
   other lessons, which are printed.
6. **Commit.** It stages `lessons.md` and the archive files and commits
   `chore(memory): lesson <id> promoted [skip ci]` with the person's git identity (from the git config or from
   `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, which `Git` scrubs and this command puts back; with `user.useConfigOnly`
   git never guesses one, and promote exits 2 when it would have to). The body is
   `Promoted-from: <inbox path>`. It adds no `L4-*` trailer: a person made this commit, not the harness, and the L4
   trailers mark harness commits. The proposal and its evidence file are then deleted.

   With `--no-commit`, it writes the files and keeps the proposal, and prints the `git add` and `git commit` lines.

The lesson reaches agents only after that commit is on the base branch and a later unit's worktree is cut from it.
Then the existing `select_lessons` and `inject_for_task` give it to the red and green prompts of matching tasks, and
`lessons.injected` records it. `kg report` then shows its outcome (D7). The loop is closed by a person at every step.

### D12. Privacy and publication

- **Redaction.** Every text field passes `app.redactor.redact_text`, then `scrub_for_commit` (the forge host becomes
  `<forge>`), before it enters the index, the report, `why`, or a proposal. Committed evidence is redacted already;
  this covers branch and attempts refs as well.
- **Nothing leaves the machine.** The index is under the person's cache root, in a 0700 folder, keyed per repository.
  `report`, `why` and `propose` read one repository's index only, and no option combines repositories.
- **Into `docs/live/` only after the check.** A report from a client repository never goes into the harness's
  `docs/live/`. A report from a test repository goes there only after `scripts/dev/scrub.py check` passes. This is a
  runbook rule, not code.

### D13. Non-breaking guarantees

- **No config key.** `L4Config` is unchanged. Every repository config that validates today still validates.
- **Doctor, ledger, lifecycle, prompts, templates, gates, verifier and CI templates** are unchanged.
- **Existing tests** keep their assertions. Only the command tables of `tests/unit/cli/test_dispatch.py`
  (`SECTION_2_1`, `ARGV`) get the five new rows. SPEC 2.1 gets four `kg` rows (the `lessons … promote ID` row exists).
- **The boundary tests of D1** are the guard: if a later change makes a run path import `l4.kg`, the suite goes red.

## How the implementer benefits

Nothing in this change reaches an agent automatically. Every route goes through a person and an existing channel:

1. **Lessons from its own repeated mistakes.**
   - `kg report` and `kg propose` find red and green attempt failures, and deterministic findings, that recur across
     units. These are the costliest implementer errors, because each one is a retry.
   - A person writes the advice in the draft and runs `l4 lessons promote`.
   - From the next unit cut from that base, the existing scoped injection (L4-MEM-003) puts the lesson into the
     prompts of matching tasks.
   - `kg report` then shows whether the same class still followed it.
2. **Gate candidates move a failure earlier.** A finding the judge raises one round later costs a fix unit and a full
   verification cycle. When a person turns a gate candidate into a deterministic gate or a lint rule, the implementer
   meets the failure in its own red/green loop: `gate.finished`, `task.attempt_failed`, and a retry prompt that names
   it.
3. **Clearer specs.**
   - Spec-gap hotspots tell spec authors which capabilities produced `spec` blame, questions and NEEDS_HUMAN rounds.
   - A person may also read them while preparing a yolo-mode readiness review. That review does not read them.
   - Fewer gaps mean fewer clarifier stops and fewer verdict questions for the implementer.
4. **A better profile order.** Profiles by role show failed attempts and the first-round PASS share per implementer
   profile (not a first-attempt pass share: the graph has no record of a task that passed first time). A person may
   reorder `roles.implementer`, and `l4 eval --compare` stays the authority before a change.
5. **Less lost work on stuck units.** `kg why <unit>` shows the attempts and repeated stops, so a person picks
   `l4 retry` or `l4 restart` with the history in front of them.

**What to expect from the data.**
- Today the history is small: 32 units in `docs/live`, one lesson, and one unit per capability. Most sections will
  show `n = 1` or `none` for a while.
- The first useful signal is likely to be recurring attempt-failure classes. The live ledgers repeat "no new test
  traces", lint-gate failures and "tests not collected individually" across several units (inferred from a text count
  of `docs/live`, not yet from the index).
- **Success criterion.** On the dummy repository's history, the report shows at least one failure class in 2 or more
  units, a person promotes one lesson from it, and in the next units that class follows the lesson's injections less
  often than before it. Until then, the feature is a report.

## Risks / Trade-offs

- **Small numbers mislead.** Every line carries *n*, recurrence needs at least 2 units, gate candidates need at least
  3, and the lesson section says "followed", not "caused".
- **Normalised text merges or splits mistakes.** It is labelled approximate. `kg why` shows the raw sources behind
  every key.
- **Missing history.** Squash merges, attempts refs that are not local, and lock refs that were not fetched leave
  gaps. They are counted in the coverage section, and the fetch command is printed. The command never fetches.
- **A proposal committed by mistake becomes agent-readable and agent-writable** (Serena's inbox rule). `propose`
  warns when the inbox is not ignored. `promote` reads the file the person sees, prints it, and asks for confirmation.
  An agent cannot run `promote`.
- **A promoted lesson is injected into every matching task, and an unscoped one into every task.** `promote` prints
  the scope before it writes, and the caps still apply.
- **The base ref may be old.** The header shows its sha and date.
- **Promote on a protected base branch.** The commit is local, and the person opens a merge request as usual. A
  promote on a unit branch is refused (D11).

## Migration Plan

- Nothing to migrate. With no `l4 kg` command run, no file is written, and no behaviour changes.
- `l4 lessons promote` is new behaviour behind an existing SPEC row. `list` and `lint` are unchanged.
- The index folder can be deleted at any time.
- Adopters get the commands with the harness version. No `l4 upgrade` is needed, because no workflow file changes.

## Open Questions

- Should `l4 kg report --json` exist (`l4/kg-report@1`) for tooling? Not in this change: the markdown is for people,
  and the index is already JSONL.
- Should promote be allowed to replace the text of an existing lesson (a `Supersedes` flow)? Not in this change. A
  matching dedupe key reinforces, and a person may still edit `lessons.md` by hand (L4-MEM-002 origin c).
- The automatic loops (L2, L3) can be reopened only on evidence: an adopter repository with at least 2 merged units on
  one capability that carry `spec` blame, or a second `LESSON_RULES` rule, and an eval that runs with memory on.
