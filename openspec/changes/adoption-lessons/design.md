## Context

The lessons, their evidence (file and line, probes, the consumer's logs) and the rejected options are in
`docs/plan/adoption-lessons.md`. This file holds only the decisions an implementer needs. Every rule here is also
stated, shorter, in a requirement of `specs/`.

## Decisions

### D1. The plugin-shadow guard (L4-ADO-001)
- **When it applies.** In `run_gate`, read the `-p <module>` options of the extra environment's `PYTEST_ADDOPTS`, and
  keep `l4_trace` and `l4_cov`.
- **What counts as a shadow.** For each kept name, look in the gate's working directory (the worktree root) for a
  module file `<name>` with a suffix from `scan._MODULE_SUFFIXES` (`.py`, `.pyc`, `.pyo`, `.pyw`, `.so`, `.pyd`, and
  any `<name>.<tag>.so`), or `<name>/__init__.<suffix>`. Reuse `l4.verifier.scan.plugin_module`: a root path is a
  shadow when it returns one of the kept names.
- **Effect.** `GateResult(status="fail", reason="<path> would replace the harness's <name> plugin: remove or rename
  it")`. No process starts. The gate log says the same.
- **Out of scope.** `coverage` is not checked: a root `coverage.py` may be a real script, and the verifier's scan
  already reports a new one. `build_gate_env` gets no `PYTHONSAFEPATH`, because the probe showed it breaks
  `python scripts/x.py` sibling imports and flat-layout suites.

### D2. `l4 setup github` and the default branch (L4-ADO-002, -005)
- **Policies.** `admin()` keeps `repo["default_branch"]`. `environment()` adds it to the pattern tuple when it is not
  the base.
- **The workflow file.** A new step reads `GET /repos/{repo}/contents/.github/workflows/l4.yml?ref=<default>`.
  - A 404 is a FAILED row: "`<default>` has no `.github/workflows/l4.yml`: GitHub runs schedule and dispatch only from
    the default branch; merge a pull request that adds it". `run_steps` then sends no dispatch.
  - Otherwise, decode the file and compare `read_pin(text)` with the base's. If they differ, print a FAILED row naming
    both shas (L4-ADO-005).
- **Dry run.** `--dry-run` does the reads and no writes, as today.

### D3. The intake hint (L4-ADO-008)
`intake_hint(message, target)` returns this text for a message that starts with `Archive would refuse this delta:`
and contains `target spec does not exist`; otherwise it returns "":

"`openspec/specs/<cap>/spec.md` is not on `<target>`: archive the change that creates `<cap>` first, or write this
delta as `## ADDED Requirements` (with a `## Purpose`). A unit cannot modify what another unit of the same plan only
adds: put that change into that unit."

`<cap>` is the word after the prefix and before the next colon. OpenSpec's own MODIFIED-scenario error already says
what to do, so it gets no hint.

### D4. How `validate_plan.py` reads like the review (L4-ADO-010)
It must reproduce `l4.yolo.readiness.read_folder` on the working tree:
1. List every file under the unit folder, recursively. Sort by the repository path's UTF-8 bytes.
2. Skip a file when any directory between the folder and the file is `.l4`, or when its name is `verification.md`,
   `questions.md` or `feedback.md` (`digest.is_excluded`).
3. In a file named `tasks.md`, replace each task marker as `digest._MARKER` does. Copy the regex; a test checks that
   the two are equal.
4. Skip a file with a NUL byte (binary).
5. Decode it as UTF-8 with `replace`. Show `text[:min(MAX_FILE_CHARS, left)]`.
   - If that is shorter than the text and `left <= 0`, the file is **omitted**.
   - Otherwise it is **cut** by `len(text) - len(shown)`, and `left` drops by the characters shown plus the length of
     the `[cut: …]` marker line, as the review appends it.
6. The budget is `MAX_FOLDER_CHARS` for a planned unit. It is `MAX_DEPENDENCY_CHARS` for a unit named in any
   `depends_on` and for a prerequisite outside its batch.

Output: one `material_over_budget: <unit>: <path>: <n> characters cut[ (as a dependency of <x>)]` or `…: omitted …`
line per entry.

A test runs both readers on the same git fixture and compares the lists. Another holds the three constants equal.

### D5. `yolo.hold` (L4-ADO-011)
- **`config_holds(cfg, unit_ids, listed) -> dict[str, Hold]`.** For each unit id that `fnmatch`es an entry of
  `yolo.hold` and is not in `listed`, the result is `Hold("held by yolo.hold", "is held by yolo.hold")`. `listed`
  holds the ids of any readable plan file, planned or excluded.
- **`plan_holds`** adds them for the units no plan holds.
- **`yolo_step`**, when there is no plan file and `yolo.hold` is not empty, returns
  `PlanStep(allow=<the units not held>, refusals=…)` instead of `allow=None`.
- **`with_plan_holds`** no longer returns early when there is no plan file and `yolo.hold` is not empty.
- **The dry run** shows the same reason.
- **Merged and archived units** are never held, as `with_plan_holds` already does for plan holds.

### D6. The CI mirror (L4-ADO-006)
- **The jobs.** `repo_ci_jobs(repo)` reads `.github/workflows/*.yml|yaml` except `l4.yml` with `yaml.safe_load`. It
  keeps a workflow whose `on` is a string, list or map naming `push` or `pull_request`. Per job, it records the `run:`
  strings, whether `services` or `container` is set, and the file. For GitLab it uses
  `l4.ci.gitlab_jobs.gitlab_jobs(repo)` and leaves out the harness's `l4` job.
- **Normalising.** Split each `run:` on newlines, `&&` and `;`. Drop empty lines and comments. Strip a leading
  `uv run `, `.venv/bin/` and `python -m ` (repeatedly), then collapse whitespace.
- **Mirrored.** A job is mirrored when each normalised command is a substring of a normalised gate command (setup,
  lint, test, e2e, or a gate named by a `yolo.profiles` entry), or one of those is a substring of it.
- **The row.** It lists each unmirrored job as `<file>: <job> (services: <names>)`, with up to 3 commands.

### D7. The System One row (L4-ADO-015)
- **Which profile.** For each name in `roles.s1_judge`, in order, call `system_one._probe(profile, environ, None,
  log)`; it starts nothing. The first that returns a backend is the one that serves.
- **Laya.** For `laya-local`, start the backend's `LayaServe` with a 120 s ready timeout, then stop it. Report
  "System One: laya-local (typed-decisions), ready in N s".
- **None serves.** The row warns with each profile's reason, the consequence, and the profile lines for Laya and for
  Jev (`TYPESAFE_API_KEY`).
- **LAN engines.** With `RUNNER_ENVIRONMENT=github-hosted`, a `remote` or `ollama` profile is "on the local network:
  unreachable from a GitHub-hosted runner".

### D8. The profiles `l4 init` writes (L4-ADO-016)
- **default `laya`:** `profiles.laya: {backend: system-one, engine: laya-local}` and `roles.s1_judge: [laya]`;
- **`--s1 jev`:** `profiles.jev: {backend: system-one, engine: jev, base_url: https://api.typesafe.ai, model:
  jev-1.13.0, api_key_env: TYPESAFE_API_KEY, vendor: typesafe}` and `roles.s1_judge: [jev]`;
- **`--s1 none`:** neither, and a `# TODO:` line.

Jev's output is never a training label (TypeSafe MCA 2.3(b)). The System One log already tags each line with its
engine.

### D9. Laya on runners (L4-ADO-019)
- **Catalog.** `LAYA_VERSION = "0.3.24"` and `LAYA_CHECKPOINT = "typed-decisions"` move to `l4.provision.catalog`;
  `prereqs.sh` takes them from there.
- **`required_tools`** adds a `laya` spec when a `laya-local` profile is in `roles.s1_judge` or `verifier.s1.shadow`.
- **Install:**
  1. `UV_TOOL_DIR=~/.local/share/l4/laya UV_TOOL_BIN_DIR=~/.local/share/l4/laya/bin uv tool install --torch-backend
     cpu 'laya[serve]==<pin>'`.
  2. Link `laya-serve` into `~/.local/bin`.
  3. Fetch the checkpoint: `snapshot_download("convaiinnovations/laya", allow_patterns=["<checkpoint>/*"])` with
     `HF_HOME=~/.cache/l4/laya/hf`.
  4. Point the `LayaServe` environment at that `HF_HOME`.
- **A present install.** `laya-serve` on `PATH` reporting the pin, and the checkpoint present in the Hugging Face cache
  (the default one or `~/.cache/l4/laya/hf`), counts as present. It is reported, nothing is installed, and `HF_HOME`
  is not overridden. A runner that `prereqs.sh` provisioned (PRQ-18) therefore downloads nothing again.
- **Cache.** `l4 ci cache-key laya` prints `l4-laya-<os>-<arch>-<image>-<pin>-<checkpoint>`, or nothing. The action
  restores and saves `~/.local/share/l4/laya` and `~/.cache/l4/laya` under that key. The CLI cache key stays as it is.
- **Estimate to check live.**

| What | Size or time | Label |
|---|---|---|
| Wheels | 44 packages, about 253 MB (torch 2.14.1+cpu 196 MB) | resolved and summed from the indexes |
| Checkpoint | 846 MB (`model.safetensors` 843 MB) | Hugging Face API |
| Ready | 5.5 s warm, 14.1 s cold | measured on the self-hosted VM |
| Peak memory | 2.48 GB RSS | measured on the self-hosted VM |
| Download | about 1.1 GB | not measured on a hosted runner |
| Cache | about 1.2 GB | not measured on a hosted runner |
| Restore | 10–20 s | not measured on a hosted runner |

### D10. `references/spec.md` (L4-ADO-014)
One line per rule, each with the judge's finding kind:
- **testability:** a scenario per SHALL, failure and "no work" cases included; a scenario must be decidable by a test
  that always runs;
- **contradiction:** proposal, design, spec and tasks say the same thing; no line-number anchors;
- **interfaces:** name every helper one unit gives another, with its signature;
- **missing_dependency:** `depends_on` when two units edit one function or file section, or when a doc describes what
  another unit creates;
- **failure_cases:** what happens when a stage does not run or raises;
- **feasibility:** only the runner's tools; say in prose what is already delivered;
- **material_cut:** the budgets, with background moved to `docs/`;
- **OpenSpec:** ADDED with a `## Purpose` where there is no baseline; every scenario name kept in a MODIFIED block;
  short requirement statements;
- **before the push:** `openspec validate <change> --strict` and `validate_plan.py`.

### D11. The docs (L4-ADO-018)

**`adopt.md`:**
- `--action-repo` is optional, needed from a checkout only;
- section 4a: `l4 init --hold-existing` in place of the backlog plan (kept as the 0.4.0 fallback, with its review
  cost);
- `l4 setup github` adds the default branch and checks its workflow; run it after the default-branch pull request is
  merged, or expect only the dispatch to fail;
- the test gate must write `.l4-out/junit.xml`;
- `L4_FORGE_TOKEN`: the secret, `forge.token_env` and `l4 upgrade`; without it no CI runs on L4's PRs;
- System One: Laya by default, `--s1 jev` with `--secret TYPESAFE_API_KEY=…`.

**`plan.md`:** a spec meant to run alone goes in `exclude` with that reason, and a held spec counts as covered.

**`README.md`:** `l4 setup github` does the forge setup.

**`quickstart.md`:**
- the schedule runs on the default branch;
- the `L4_FORGE_TOKEN` steps;
- `.l4/bin/l4 setup github` becomes `l4 setup github`;
- `--action-repo` from a checkout only.

**`runbook.md`:**
- 7.15: the default branch's policy, and its copy of the pin;
- the private harness: https with the person's credentials;
- laptop pushes: the person's credentials after L4-ADO-003;
- push refusals per forge;
- the review limits.

**`yolo-mode.md`:** the review limits.

**Template comments:** with `GITHUB_TOKEN`, no harness push starts a run.

**`free-resources.md`:** the Jev rows, after the live run.

## Risks

- **D6 is a heuristic.** The row warns and never fails a run.
- **Laya by default** downloads about 1.1 GB on the first hosted job of each repository and adds about 2.5 GB of
  memory while step 8 runs [measured on the self-hosted VM]. GitHub's standard runner has 16 GB for public
  repositories but 7 GB for private ones [inferred from GitHub's runner documentation, not checked here]. On a
  private repository, Laya's peak next to an agent and the gates may not fit. `LayaServe` runs only around step 8 and
  the clarifier's questions, never beside an agent (`system_one.py` D7), which limits the overlap. `--s1 none` or
  `--s1 jev` turns it off.
- **D2 adds one contents read per setup run.** A 403 there (a token without contents read) is a FAILED row, not a
  crash.
