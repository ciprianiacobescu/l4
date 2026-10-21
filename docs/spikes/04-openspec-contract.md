<!-- Saved by the orchestrator from the spike agent's returned text: the agent's own write to this path was refused by a report-file guard (2026-10-03). Content unchanged. -->

# 04 OpenSpec 1.14.0 CLI contract and the L4-OSP-* provider design

Spike run 2026-10-03 on macOS (Apple M4 Max), Node v22.22.0 (installed with nvm), npm 10.9.4. OpenSpec 1.14.0 ran from a harness-owned prefix (`$SCRATCH/harness-prefix`). Labels: **[V]** means I ran it in this spike, **[S]** means I read it in the 1.14.0 `dist/` source but did not run it, **[I]** means inferred.

## Question

1. What do the OpenSpec 1.14.0 commands the harness needs actually return? That covers JSON shapes, exit codes, error shapes, time per call, and the repo state after `archive`.
2. Is the provider design in SPEC §4.4 (L4-OSP-001…006) right? Specifically:
   - Does `archive --yes` skip the task check?
   - Is the root check right?
   - Can the harness task parser agree with `instructions apply` on CRLF files, indented subtasks and `[x]`/`[X]`?
   - Does the prefix CLI work on a repo with no `node_modules`?

## Method (exact commands)

Everything ran in `$SCRATCH/spikes/openspec-contract/`, where `$SCRATCH=/tmp/scratch`.

Every CLI call went through a recorder, `osrun.py`, with:
- `cwd=<repo>` and `stdin=/dev/null`;
- environment `PATH HOME TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1 LANG=C.UTF-8`.

The recorder captures stdout, stderr, exit code and wall time. It replaces the repo path with `{{REPO}}`, the scratch path with `{{SCRATCH}}`, `/Users/<name>` with `/Users/{{USER}}`, and e-mail addresses with `{{EMAIL}}`.

**Fixture repo.** `setup.sh` builds it and commits it once. Every case that changes files runs in a fresh `cp -R` of that commit. It has 10 changes and 1 base spec (`greeting`):

| change | purpose |
|---|---|
| `add-farewell` | Valid. 2 capabilities: `greeting` (MODIFIED + ADDED) and a new `farewell` with `## Purpose`. 5 tasks, 2 checked. |
| `broken-change` | Invalid: a `### Scenario:` heading with 3 `#`, and a new capability with no `## Purpose`. |
| `chore-tasks-only` | `skip_specs: true`, only `tasks.md` (no proposal), 0 of 2 tasks done. |
| `with-extras` | Valid, 2 of 2 tasks done. Also has `questions.md`, `verification.md`, `.l4/state.json` and `evidence/round-1/junit.xml`. |
| `no-purpose` | Valid scenario, but the new capability has no `## Purpose`. 1 of 1 task done. |
| `modify-missing` | A `MODIFIED` delta that names a requirement missing from `greeting` (the L4-OSP-006 case). |
| `no-shall` | Requirement text without SHALL/MUST. That is a WARNING, so it fails only under `--strict`. |
| `task-grammar`, `task-grammar-crlf` | `skip_specs`. A 39-line `tasks.md` of grammar edge cases, plus a byte-identical CRLF copy. |

`setup.sh <target-dir>` is shown verbatim below with two substitutions:
- the git e-mail is replaced by a placeholder;
- the non-ASCII characters in the grammar list are shown as `\u` escapes, which is equivalent Python.

```bash
#!/usr/bin/env bash
set -euo pipefail
SP=$SCRATCH
OS=${OS:-$SP/harness-prefix/node_modules/.bin/openspec}
export TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1
R=$1
rm -rf "$R"; mkdir -p "$R"; cd "$R"
git init -q -b main
git config user.email <git-email>
git config user.name CiprianSpot
cat > pyproject.toml <<'EOF'
[project]
name = "greeter"
version = "0.1.0"
requires-python = ">=3.11"
EOF
mkdir -p src/greeter && echo 'def greet(name): return f"Hello, {name}!"' > src/greeter/__init__.py
"$OS" init --tools none --no-animation </dev/null >/dev/null 2>&1
mkdir -p openspec/specs/greeting
cat > openspec/specs/greeting/spec.md <<'EOF'
# greeting Specification

## Purpose
The greeting capability produces a friendly greeting for a named user of the CLI.

## Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line.

#### Scenario: Named greeting
- **WHEN** the user runs `greet Ada`
- **THEN** the output is `Hello, Ada!`
EOF
# 1. valid change: 2 capabilities, 5 tasks (2 checked)
"$OS" new change add-farewell --json </dev/null >/dev/null 2>&1
C=openspec/changes/add-farewell
cat > $C/proposal.md <<'EOF'
# Proposal

## Why
Users want the CLI to say goodbye and to shout greetings.

## What Changes
- Greeting can be uppercased with `--shout`.
- New `farewell` command.

## Capabilities

### New Capabilities
- `farewell`: saying goodbye to a named user

### Modified Capabilities
- `greeting`: adds shouting and tightens the named greeting

## Impact
src/greeter/
EOF
printf '# Design\n\nPlain functions in `src/greeter/__init__.py`.\n' > $C/design.md
mkdir -p $C/specs/greeting $C/specs/farewell
cat > $C/specs/greeting/spec.md <<'EOF'
## MODIFIED Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line, trimming surrounding whitespace.

#### Scenario: Named greeting
- **WHEN** the user runs `greet " Ada "`
- **THEN** the output is `Hello, Ada!`

## ADDED Requirements

### Requirement: Shout
The system SHALL print the greeting in upper case when `--shout` is given.

#### Scenario: Shouted greeting
- **WHEN** the user runs `greet Ada --shout`
- **THEN** the output is `HELLO, ADA!`
EOF
cat > $C/specs/farewell/spec.md <<'EOF'
## Purpose
The farewell capability says goodbye to a named user of the greeter command line tool.

## ADDED Requirements

### Requirement: Say goodbye
The system SHALL print `Goodbye, <name>!` for `farewell <name>`.

#### Scenario: Named farewell
- **WHEN** the user runs `farewell Ada`
- **THEN** the output is `Goodbye, Ada!`
EOF
cat > $C/tasks.md <<'EOF'
# Tasks

## 1. Greeting

- [x] 1.1 Trim whitespace around the name
- [x] 1.2 Add `--shout`

## 2. Farewell

- [ ] 2.1 Add `farewell` function
- [ ] 2.2 Wire `farewell` command
- [ ] 2.3 Document both commands
EOF
# 2. invalid change: 3-hashtag scenario + missing Purpose
"$OS" new change broken-change --json </dev/null >/dev/null 2>&1
C=openspec/changes/broken-change
printf '# Proposal\n\n## Why\nA deliberately broken change for the contract spike.\n\n## What Changes\n- New `badcap` capability.\n\n## Capabilities\n\n### New Capabilities\n- `badcap`: broken on purpose\n\n## Impact\nnone\n' > $C/proposal.md
mkdir -p $C/specs/badcap
cat > $C/specs/badcap/spec.md <<'EOF'
## ADDED Requirements

### Requirement: Broken scenario heading
The system SHALL do something observable.

### Scenario: Three hashtags instead of four
- **WHEN** anything happens
- **THEN** nothing is checked
EOF
printf '# Tasks\n\n## 1. Broken\n\n- [ ] 1.1 Never runs\n' > $C/tasks.md
# 3. skip_specs: true, tasks only
"$OS" new change chore-tasks-only --json </dev/null >/dev/null 2>&1
C=openspec/changes/chore-tasks-only
printf 'skip_specs: true\n' >> $C/.openspec.yaml
printf '# Tasks\n\n## 1. Chore\n\n- [ ] 1.1 Bump the linter\n- [ ] 1.2 Re-run the formatter\n' > $C/tasks.md
# 4. change with extra harness files
"$OS" new change with-extras --json </dev/null >/dev/null 2>&1
C=openspec/changes/with-extras
printf '# Proposal\n\n## Why\nKeep an audit line for every greeting so operators can count usage.\n\n## What Changes\n- New `audit` capability.\n\n## Capabilities\n\n### New Capabilities\n- `audit`: append-only usage log\n\n## Impact\nsrc/greeter/\n' > $C/proposal.md
mkdir -p $C/specs/audit $C/.l4 $C/evidence/round-1
cat > $C/specs/audit/spec.md <<'EOF'
## Purpose
The audit capability records one line per greeting so that operators can count CLI usage.

## ADDED Requirements

### Requirement: Audit line
The system SHALL append one line per greeting to `audit.log`.

#### Scenario: One greeting, one line
- **WHEN** the user runs `greet Ada`
- **THEN** `audit.log` gains exactly one line
EOF
printf '# Tasks\n\n## 1. Audit\n\n- [x] 1.1 Append the audit line\n- [x] 1.2 Test the audit line\n' > $C/tasks.md
printf '# Questions — with-extras\n\n## Q-001: Rotate audit.log?\n### Answer\nNo.\n' > $C/questions.md
printf '# Verification — with-extras\nVerdict: PASS\n' > $C/verification.md
echo '{"schema":"l4/state@1","phase":"verifying"}' > $C/.l4/state.json
echo '<testsuite tests="1"/>' > $C/evidence/round-1/junit.xml
# 5. new capability WITHOUT ## Purpose
"$OS" new change no-purpose --json </dev/null >/dev/null 2>&1
C=openspec/changes/no-purpose
printf '# Proposal\n\n## Why\nNotify users.\n\n## What Changes\n- New `notify` capability.\n' > $C/proposal.md
mkdir -p $C/specs/notify
printf '## ADDED Requirements\n\n### Requirement: Notify on greet\nThe system SHALL print a notice after each greeting.\n\n#### Scenario: Notice printed\n- **WHEN** the user runs `greet Ada`\n- **THEN** a notice line follows the greeting\n' > $C/specs/notify/spec.md
printf '# Tasks\n\n## 1. Notify\n\n- [x] 1.1 Print the notice\n' > $C/tasks.md
# 6. MODIFIED names a requirement missing from the base spec
"$OS" new change modify-missing --json </dev/null >/dev/null 2>&1
C=openspec/changes/modify-missing
printf '# Proposal\n\n## Why\nModify a requirement that does not exist.\n\n## What Changes\n- greeting\n' > $C/proposal.md
mkdir -p $C/specs/greeting
printf '## MODIFIED Requirements\n\n### Requirement: Greet in Klingon\nThe system SHALL greet the user in Klingon.\n\n#### Scenario: Klingon greeting\n- **WHEN** the user runs `greet Ada --klingon`\n- **THEN** the output is `nuqneH, Ada!`\n' > $C/specs/greeting/spec.md
printf '# Tasks\n\n## 1. Klingon\n\n- [x] 1.1 Translate\n' > $C/tasks.md
# 7. requirement without SHALL/MUST
"$OS" new change no-shall --json </dev/null >/dev/null 2>&1
C=openspec/changes/no-shall
printf '# Proposal\n\n## Why\nA banner.\n\n## What Changes\n- New `banner` capability.\n' > $C/proposal.md
mkdir -p $C/specs/banner
printf '## Purpose\nThe banner capability prints a decorative banner above every greeting the CLI prints.\n\n## ADDED Requirements\n\n### Requirement: Banner line\nThe system prints a banner above the greeting.\n\n#### Scenario: Banner shown\n- **WHEN** the user runs `greet Ada`\n- **THEN** a banner line precedes the greeting\n' > $C/specs/banner/spec.md
printf '# Tasks\n\n## 1. Banner\n\n- [x] 1.1 Print banner\n' > $C/tasks.md
# 8/9. tasks.md grammar edge cases, LF and CRLF twins
for N in task-grammar task-grammar-crlf; do
  "$OS" new change $N --json </dev/null >/dev/null 2>&1
  printf 'skip_specs: true\n' >> openspec/changes/$N/.openspec.yaml
done
python3 - <<'PYEOF'
lines = ["\ufeff- [ ] 0.1 BOM-prefixed first line", "# Tasks", "", "## 1. Grammar", "",
 "- [ ] 1.1 plain unchecked", "- [x] 1.2 lower x", "- [X] 1.3 upper X",
 "  - [ ] 1.3.1 indented two spaces", "    - [x] 1.3.2 indented four spaces", "\t- [ ] 1.3.3 tab indented",
 "- [ x] 1.4 padded x", "- [ x ] 1.5 padded both", "- [-] 1.6 dash marker", "- [~] 1.7 tilde marker",
 "- [] 1.8 empty brackets", "* [ ] 1.9 star bullet", "+ [ ] 1.10 plus bullet", "1. [ ] 1.11 ordered dot",
 "2) [x] 1.12 ordered paren", "-[ ] 1.13 no space after bullet", "- [x]1.14 no space after bracket",
 "- [ ]", "- [x]", "- [ ]* 1.15 kiro optional star", "\u00a0\u00a0- [ ] 1.16 nbsp indented",
 "- [A](https://example.com) link bullet", "- [ ](https://example.com) blank-box link",
 "- [WIP] multi-char marker", "- [ ] 1.17 trailing spaces   ", "- [ ] 1.18 has a form\x0cfeed inside",
 "- [ ] 1.19 has a line\u2028separator inside", "```md", "- [ ] 9.9 inside code fence", "```",
 "<!--", "- [ ] 9.8 inside html comment", "-->", "- [ ] 1.20 last line without newline"]
body = "\n".join(lines)
open("openspec/changes/task-grammar/tasks.md", "w", encoding="utf-8", newline="").write(body)
open("openspec/changes/task-grammar-crlf/tasks.md", "w", encoding="utf-8", newline="").write(body.replace("\n", "\r\n"))
PYEOF
git add -A && git commit -q -m "baseline fixture"
```
(The scratch file writes some of the files above with heredocs; the content is the same.)

**Recorded matrix (`record.sh`).** `rec <case> <cwd> <args…>` runs `osrun.py --record`. `arch` runs `archive` in a fresh copy, then records `git add -A && git status --porcelain=v1`.
```bash
rec list $B list --json ; rec list-sort-name $B list --json --sort name ; rec list-specs $B list --specs --json
rec show-add-farewell $B show add-farewell --json
rec show-add-farewell-type-change-deltas-only $B show add-farewell --type change --json --deltas-only
rec show-broken-change $B show broken-change --type change --json ; rec show-chore-tasks-only $B show chore-tasks-only --type change --json
rec show-greeting-spec $B show greeting --type spec --json ; rec show-unknown $B show nope --type change --json
for c in add-farewell broken-change chore-tasks-only with-extras no-purpose modify-missing no-shall task-grammar; do rec validate-$c-strict $B validate $c --strict --json; done
rec validate-no-shall-nonstrict $B validate no-shall --json ; rec validate-all-strict $B validate --all --strict --json
rec validate-unknown $B validate nope --strict --json ; rec validate-noarg $B validate --strict --json
rec status-add-farewell $B status --change add-farewell --json ; rec status-chore-tasks-only $B status --change chore-tasks-only --json ; rec status-unknown $B status --change nope --json
for c in add-farewell chore-tasks-only with-extras broken-change task-grammar task-grammar-crlf; do rec apply-$c $B instructions apply --change $c --json; done
rec apply-unknown $B instructions apply --change nope --json
arch with-extras-yes with-extras --yes ; arch with-extras-yes-json with-extras --yes --json
arch add-farewell-yes add-farewell --yes ; arch add-farewell-yes-json add-farewell --yes --json
arch add-farewell-json-noyes add-farewell --json ; arch add-farewell-noyes-text add-farewell
arch broken-change-yes broken-change --yes ; arch broken-change-yes-json broken-change --yes --json
arch chore-tasks-only-yes-json chore-tasks-only --yes --json ; arch no-purpose-yes-json no-purpose --yes --json
arch modify-missing-yes-json modify-missing --yes --json ; arch no-shall-yes-json no-shall --yes --json ; arch unknown-yes-json nope --yes --json
# pre-create openspec/changes/archive/$(TZ=UTC date +%F)-with-extras, then: archive with-extras --yes --json  -> archive-target-exists-yes-json
# post-archive: list --all --json --sort name ; list --archived --json ; list --specs --json ; validate --archived --json (in a-with-extras-yes-json)
#               validate --specs --strict --json ; show notify --type spec --json ; validate notify --type spec --strict --json (a-no-purpose-yes-json)
#               validate --specs --strict --json (a-no-shall-yes-json)
#               validate --all --strict --json ; validate --archived --json ; validate greeting --type spec --strict --json (a-add-farewell-yes-json)
# fix unit: new change add-farewell-fix-1 --json (twice) ; new change Add_Farewell --json ; validate add-farewell-fix-1 --strict --json ;
#           instructions apply --change add-farewell-fix-1 --json ; append skip_specs + write proposal.md/tasks.md ; validate/show/apply again
```

**Other experiments** (scripts are in the scratch dir):
- **Timings:** 9 runs per command, median/min/max, against a `node -e 0` baseline.
- **Planted package (SCN-SEC-08):** a repo copy with a fake `node_modules/@fission-ai/openspec/bin/openspec.js` that writes a `PWNED` marker, plus `node_modules/.bin/openspec`. Then:
  - `$PREFIX/node_modules/.bin/openspec list --json`;
  - `PATH=./node_modules/.bin:$PATH openspec list --json`;
  - `env -i PATH=/usr/bin:/bin $PREFIX/.bin/openspec --version`;
  - `env -i PATH=/usr/bin:/bin <abs node> $PREFIX/node_modules/@fission-ai/openspec/bin/openspec.js list --specs --json`.
- **Root resolution:** a parent dir holds a full OpenSpec root. Inner git repos have, respectively: no `openspec/`; an empty `openspec/`; `changes/` only; `config.yaml` only; a legacy `project.md` + `changes/x/`; `specs/` only. `XDG_*` were isolated. Also tested: a symlinked cwd (`/tmp` → `/private/tmp`) and a subdirectory cwd.
- **Global `defaultStore`:** with `HOME=<probe>`, ran `openspec store register <other repo> --id other --yes` and `openspec config set defaultStore other`. Then `list --json` in a git repo with no `openspec/`, first plain, then with `XDG_CONFIG_HOME`/`XDG_DATA_HOME` pointed at empty dirs.
- **What gets written to HOME:** with `HOME=<empty probe>`, ran `--json` calls (list, validate --all, apply, archive) with the opt-out environment. Also ran `list --json` and text-mode `list` with no opt-out environment. Then `find <probe> -type f`.
- **Stdin:** `archive add-farewell` with and without `--json`, with stdin as `/dev/null` and as an open pipe, under an 8 s timeout.
- **Parser parity:** Python ports compared against `instructions apply --json`:
  - *exact*: JS semantics, i.e. `\s` includes U+FEFF, `.` excludes U+2028/2029, ASCII `\d`, `split('\n')`, JS `trim`;
  - *naive*: the regex pasted into Python plus `splitlines()`.
- **Pinning:** `npm install --prefix <d> @fission-ai/openspec@1.14.0 --package-lock-only`, with and without `--save-exact`.

## Observations

### Shapes [V]
Every `--json` call printed exactly one JSON document on stdout and nothing on stderr.

| command | exit | shape / notes |
|---|---|---|
| `list --json` | 0 | `{changes:[{name,completedTasks,totalTasks,lastModified,status:"in-progress"\|"complete"\|"no-tasks"}],root}`. Default sort is `recent`, by **file mtime**, which is arbitrary after a CI checkout. `--sort name` is stable. `--all` adds `archived:true\|false`, and archived names are `YYYY-MM-DD-<id>`. |
| `list --specs --json` | 0 | `{specs:[{id,requirementCount}],root}` |
| `show <c> --json` | 0 | `{id,title(=id),deltaCount,deltas:[{spec,operation,description,requirement:{name,text,scenarios:[{name,rawText}]},requirements:[…]}],root}`. This gives capability › requirement › scenario names, which is exactly the L4-CRT-001 input. A 3-`#` scenario comes back as `scenarios:[]`. |
| `show <c> --type change --json --deltas-only` | 0 | **Byte-identical** to `show <c> --json`. The flag does nothing for changes. |
| `show <spec> --type spec --json` | 0 | `{id,title,overview(=Purpose),requirementCount,requirements,metadata:{version,format},root}` |
| `show` on a change with no `proposal.md` | **1** | `{status:[{severity:"error",code:"show_error",message:"Change … has no proposal.md yet…"}]}`, with no `root` key. |
| `validate <c> --strict --json` | 0/1 | `{items:[{id,type:"change"\|"spec",valid,issues:[{level,path,line?,message}],durationMs}],summary:{totals:{items,passed,failed},byType},version:"1.0",root}` |
| `validate --all --strict --json` | 1 if any item fails | 10 items: 9 changes and 1 spec. Archived changes are not included. |
| `validate --strict --json` with no item | 1 | **Not JSON.** It prints "Nothing to validate…" as text on stderr and nothing on stdout. |
| `status --change <c> --json` | 0 | `{changeName,schemaName,planningHome,changeRoot,artifactPaths,isPlanningComplete,isComplete,applyRequires,nextSteps,actionContext,artifacts:[{id,outputPath,status:"done"\|"ready"\|"blocked"\|"skipped",requires,missingDeps?}],root}`. `isComplete:true` with 2 of 5 tasks open means **planning** is complete, not the work. |
| `instructions apply --change <c> --json` | 0, even for an invalid change | `{changeName,changeDir,schemaName,contextFiles,progress:{total,complete,remaining},tasks:[{id,description,done,sourcePath,line}],taskTrackingConfigured,state,missingArtifacts?,missingPrerequisites?,warnings?,instruction,root}`. All three `state` values were seen: `ready`, `all_done`, and `blocked` (no `tasks.md`; then `missingArtifacts:["tasks"]`). `missingPrerequisites` was not in the research notes. |
| `archive <c> --yes --json`, success | 0 | `{archive:{change,archivedAs:"YYYY-MM-DD-<c>",path,specsUpdated,totals?:{added,modified,removed,renamed}},root}`. With `skip_specs`: `specsUpdated:false` and no `totals`. |
| `archive`, failure | 1 | `{archive:null,root,status:[{severity,code,message,fix?}]}` |
| `new change <id> --json` | 0 | `{change:{id,path,metadataPath,schema},root}`. It creates **only** `.openspec.yaml` (`schema`, `created:<date in process time zone>`). |
| unknown id in `show` / `status` / `apply` / `validate` | 1 | codes `show_error` / `change_error` / `change_error` / `unknown_item` |
| `new change` when it exists / bad name | 1 | `{change:null,status:[{code:"change_error",…}]}` |

**Exit codes [V].**
- Every failure exits **1**: validation failure, unknown item, every `archive_*` code, `show_error`, `change_error`, `no_openspec_root`.
- Success exits 0, including a validate run that only has INFO or WARNING issues.
- Exit 127 happens only when the `.bin` shim cannot find `node`.
- So the harness must classify failures by `status[].code`, not by exit code.

**Validation [V].**

| change | `validate --strict` | issues |
|---|---|---|
| `broken-change` | fail | INFO "Header `### Scenario: …` … is ignored" (line 6), plus ERROR "ADDED … must include at least one scenario". **The missing Purpose is not reported.** |
| `no-purpose` | **pass, no issues** | The CLI does not check for a missing Purpose on a new capability. |
| `modify-missing` | **pass** | Only an INFO: `Archive would refuse this delta: greeting MODIFIED failed for header "### Requirement: Greet in Klingon" - not found` |
| `no-shall` | fail (passes without `--strict`) | WARNING "should contain SHALL or MUST" |
| `task-grammar` | fail | 2 WARNINGs: `Task "9.9" is under group 1, but its leading number points to group 9`. Duplicate task IDs are also a WARNING [S]. |
| `chore-tasks-only` (no proposal) | pass | INFO "skip_specs … zero deltas accepted" |
| fresh `new change` (only `.openspec.yaml`) | fail | ERROR "Change must have at least one delta" |
| fix unit with `skip_specs` + `proposal.md` + `tasks.md` | pass | `show` works (`deltaCount:0`); `apply` gives `state:"ready"` |

### Archive matrix [V]

| case | exit | result | repo afterwards |
|---|---|---|---|
| `with-extras --yes`, with or without `--json` (2/2 tasks, valid) | 0 | archived as `2026-10-03-with-extras` | The whole folder moved to `openspec/changes/archive/2026-10-03-with-extras/`, **including `questions.md`, `verification.md`, `.l4/state.json` and `evidence/round-1/junit.xml`**. A new `openspec/specs/audit/spec.md` was written with the Purpose. |
| `add-farewell --yes` (**2/5 tasks**) | **0** | printed "Warning: 3 incomplete task(s) found. Continuing due to --yes flag." and archived | `greeting` spec modified, `farewell` spec created, folder moved |
| `add-farewell --yes --json` (2/5) | **0** | archived, and **the JSON has no incomplete-task warning** | same |
| `add-farewell --json` (no `--yes`) | 1 | `archive_tasks_incomplete` | unchanged |
| `add-farewell`, text mode, stdin `/dev/null` | 1 | stderr: "no answer could be read from stdin" | unchanged |
| `add-farewell`, text mode, stdin is an **open pipe** | — | **Hangs** at the `(y/N)` prompt; killed after 8 s. With `--json` and the same pipe it exits 1 in 0.3 s. | — |
| `broken-change --yes`, with or without `--json` | 1 | `archive_validation_failed` | unchanged |
| `chore-tasks-only --yes --json` (0/2 tasks, `skip_specs`) | **0** | archived, `specsUpdated:false`; no `--skip-specs` flag needed | folder moved |
| `no-shall --yes --json` (fails strict) | **0** | archived, because archive validates **non-strictly** | the new `banner` main spec fails `validate --specs --strict` |
| `no-purpose --yes --json` (passes strict) | **0** | archived | The `notify` main spec gets Purpose `TBD - created by archiving change no-purpose. Update Purpose after archive.` **`validate notify --type spec --strict` and `validate --specs --strict` now exit 1** with a "Purpose section is still a placeholder" WARNING. |
| `modify-missing --yes --json` (passes strict) | 1 | `archive_spec_update_failed`, fix text "No files were changed." | unchanged |
| `nope --yes --json` | 1 | `archive_change_not_found` | — |
| archive target folder already exists | 1 | `archive_target_exists` | unchanged |
| after archiving `add-farewell` at 2/5: `validate --archived --json` | 1 | ERROR "3 incomplete tasks (2/5 completed)". It stays red until someone edits the archive. | — |

With `TZ=UTC` the archive folder date was `2026-10-03`.

### Task grammar through `instructions apply --json` [V]

The 39-line grammar file gives `progress {total:29, complete:8, remaining:21}` and 27 entries in `tasks[]`. The CRLF copy gives **identical** counts, line numbers and descriptions; `trim` strips the `\r`.

| line form | counted? | done? | in `tasks[]`? |
|---|---|---|---|
| `- [ ]`, `- [x]`, `- [X]`, `- [ x]`, `- [ x ]` | yes | only for `x`/`X` | yes |
| indented by 2 or 4 spaces, a tab, or **NBSP** | yes; each subtask counts, and so do parents | — | yes |
| `\ufeff- [ ] 0.1` (BOM on line 1) | yes, because JS `\s` matches U+FEFF | — | yes |
| `[-]`, `[~]`, `[]` | yes | **no** | yes |
| `* [ ]`, `+ [ ]`, `1. [ ]`, `2) [x]`, `-[ ]`, `- [x]1.14` | yes | — | yes |
| `- [ ]* 1.15` (Kiro's optional marker) | yes, as a **required** task | no | description becomes `"* 1.15 …"` |
| bare `- [ ]` / `- [x]` with no text | **yes, in `progress`** | — | **no** |
| `- [ ](https://…)` | yes | no | description is the URL text |
| `- [A](…)`, `- [WIP] …` | no | — | — |
| inside a code fence or a multi-line `<!-- -->` | **yes** | — | yes |
| text containing U+2028 / U+000C | yes | — | truncated at U+2028; U+000C kept |

- `tasks[].id` is an **ordinal** ("1", "2", …) over tasks that have text. It is not the "1.1" number, which stays inside `description`. Inserting a task renumbers everything after it.
- `line` is 1-based, counted over `split('\n')`.

**Parser parity** (`task-parser-parity.txt`):
- The *exact* port matches the CLI on all three files, on `progress` and on every `tasks[]` field.
- The *naive* port gets 28 instead of 29. It misses the BOM line (Python `\s` does not match U+FEFF) and keeps the text after U+2028.
- With `splitlines()`, the naive port also shifts every line number by one after each U+000C or U+2028 line.

**Marker offset trap [V, Python port].** For `- [ ]`, regex group 1 is empty and `m.start(1)` points at `]`, not at the space. For `- []` there is no byte that could hold the marker at all.

### Root resolution [V]

- `root.path` is the **repo root**, i.e. the directory that contains `openspec/`, not `<repo>/openspec`. It is the **realpath**: running from `/tmp/…` reports `/private/tmp/…`.
- Running from a subdirectory walks up to the repo root with `source:"nearest"`.
- An inner repo with **no `openspec/`, or an empty one**, resolves to the **parent's** root: `source:"nearest"`, exit 0, and it returns the parent's 9 changes.
- An inner `openspec/` that has only `changes/`, only `specs/`, or only `config.yaml` resolves to the inner repo. So does the legacy `project.md` + `changes/` layout, with no complaint from the CLI.
- **Global `defaultStore` hijack:** if the runner user has a registered store and `defaultStore` set, `list --json` in a repo with no `openspec/` returns **the other repo's changes**. It exits 0 with `root:{path:<other>,source:"global_default",store_id:"other"}`.
- With `XDG_CONFIG_HOME` and `XDG_DATA_HOME` pointed at empty dirs, the same call gives `no_openspec_root` and exit 1.
- Global config lives in `$XDG_CONFIG_HOME/openspec` or `~/.config/openspec`; the store registry in `$XDG_DATA_HOME/openspec` or `~/.local/share/openspec`.

### Prefix, node and environment [V]

- **The prefix works on a repo with no `node_modules`.** All cases above ran that way.
- **Planted package:** with a fake `node_modules/@fission-ai/openspec` in the repo, the absolute prefix path ran the real CLI and the marker was **not** created. A bare `openspec` with `./node_modules/.bin` first on PATH **ran the planted code**. A `node_modules` at the repo root changes no result.
- **`.bin/openspec` needs `node` on PATH.** It is a symlink to `bin/openspec.js`, which starts with `#!/usr/bin/env node`. With `PATH=/usr/bin:/bin` it exits **127**. Calling `<absolute node> <prefix>/node_modules/@fission-ai/openspec/bin/openspec.js` works without node on PATH and takes the same time.
  - Node here comes from nvm, so it is not on a non-login PATH. That is the shell-executor runner situation.
- **Pinning:** `npm install --prefix … @fission-ai/openspec@1.14.0` writes `"^1.14.0"` to `package.json`; `--save-exact` writes `"1.14.0"`. The lockfile pins 1.14.0 either way. OpenSpec's own dependencies (commander, chalk, zod, …) float unless the install uses `npm ci` with a lockfile.
- **HOME writes:** `--json` runs wrote **nothing** to HOME, with or without the opt-out environment.
  - A text-mode run with no opt-out wrote `~/.config/openspec/config.json` (`telemetry.anonymousId`, `noticeSeen`) and printed a telemetry notice on stderr.
  - Off switches [S]: `OPENSPEC_TELEMETRY=0`, `DO_NOT_TRACK=1` or `CI` disable telemetry; `OPENSPEC_NO_UPDATE_CHECK`, `DO_NOT_TRACK` or `CI` disable the update check.
- No ANSI escape codes appeared in any recorded stdout (no terminal attached).

### Timings [V]
9 runs each, medians in ms:

| command | median ms |
|---|---|
| `node -e 0` | 23 |
| `openspec --version` | 157 |
| `list --json` | 181 |
| `list --specs --json` | 159 |
| `show --type change --json` | 169 |
| `validate <c> --strict --json` | 180 |
| `validate --all --strict --json` (10 items) | 206 |
| `status --json` | 181 |
| `instructions apply --json` | 183 |
| direct `node …/bin/openspec.js list --json` | 172 |

- About 150 ms of each call is Node startup plus module loading; the real work is 10–50 ms.
- An intake of 5 calls costs about 0.9 s on this machine. Expect 2–4× that on a small runner [I].
- That is acceptable, so no long-lived process is needed.

## Verdict

**ADAPT.** The §4.4 approach holds. It runs the pinned CLI from a harness-owned prefix and reads JSON only. It never lets `archive` gate anything; instead it runs its own done gate and a strict validate first. Fix units use `skip_specs`.

The spike confirmed these claims [V]:
- `archive --yes` archives with 2 of 5 tasks open, and also with 0 of 2.
- `archive` validates only non-strictly.
- A MODIFIED delta that names a missing requirement passes `--strict` with only an INFO, then fails at archive.
- `skip_specs` fix units validate and archive.
- The prefix CLI ignores a planted `node_modules`.
- An *exact* Python port of the task grammar matches `instructions apply` on LF, CRLF and every edge case tried.

Six things in SPEC need changing:
1. **L4-OSP-002 checks the wrong path.** `root.path` is the repo root (realpath), not `openspec/`. When the CLI walks up into a parent's root, `source` is still `"nearest"`, so only the path comparison catches it.
2. **Global OpenSpec state on the runner can redirect the CLI** (`defaultStore`, which shows up as `source:"global_default"`). The environment must isolate `XDG_CONFIG_HOME` and `XDG_DATA_HOME`.
3. **A new capability without `## Purpose` passes `validate --strict` and archives.** It then leaves a main spec that fails strict validation, which turns doctor SPEC-002 red after merge. The harness needs its own Purpose check plus a strict check of the touched specs after archive.
4. **The task identity, marker offset and optional/parent rules in L4-OSP-004 and L4-TMW-001 are wrong or missing.**
   - The CLI `id` is an ordinal, not the task number.
   - `m.start(1)` is the wrong offset for the marker byte.
   - `[]` cannot be changed with a one-byte write.
   - OpenSpec has no optional tasks.
   - Parent checkboxes count, so the harness has to tick them.
5. **Text-mode `archive` hangs when stdin is an open pipe.** Every call must use `--json`, `stdin=/dev/null` and a timeout.
6. **`.bin/openspec` needs `node` on PATH**, or it exits 127. The harness must run `<resolved node> <prefix>/…/bin/openspec.js` directly.

## Consequences for SPEC + implementation

**L4-OSP-001 (invocation).** Replace the current text with the following.

- **Install:**
  - `npm install --prefix $L4_CACHE/tools/openspec-<v> --save-exact --no-audit --no-fund @fission-ai/openspec@<v>`.
  - Better still: `npm ci` against a `package-lock.json` shipped with the harness, which also pins OpenSpec's dependencies.
  - Afterwards, check that `--version` equals `<v>`.
- **How to run it:**
  - Use `[<node>, $PREFIX/node_modules/@fission-ai/openspec/bin/openspec.js, …]`, where `<node>` is the absolute path that doctor ENV-003 resolved and checked (≥ 20.19.0).
  - Never use the `.bin` shim, `npx`, or a bare `openspec`.
  - Always `cwd=realpath(repo)`, `stdin=DEVNULL`, timeout ≤ 60 s.
- **Environment:**
  - Set exactly `TZ=UTC DO_NOT_TRACK=1 OPENSPEC_TELEMETRY=0 OPENSPEC_NO_UPDATE_CHECK=1 NO_COLOR=1 XDG_CONFIG_HOME=$L4_CACHE/openspec-xdg/config XDG_DATA_HOME=$L4_CACHE/openspec-xdg/data` (both dirs empty and owned by the harness).
  - Pass PATH and HOME through. Pass nothing else.
- **Commands:**
  - `list --json --sort name`, plus `--all` for archived changes (named `YYYY-MM-DD-<id>`).
  - `show <id> --type change --json`. Drop `--deltas-only`, which does nothing. `show` needs a `proposal.md`.
  - `show <cap> --type spec --json`.
  - `validate <id> --strict --json` and `validate --all --strict --json`. Never call `validate` without an item: that prints text and exits 1.
  - `validate <cap> --type spec --strict --json`.
  - `instructions apply --change <id> --json`: `state` is `ready|all_done|blocked`, plus `missingArtifacts`/`missingPrerequisites`. `apply` does not validate.
  - **`archive <id> --yes --json`** (add `--json`).
  - `new change <id> --json`.
- **Do not use `status`.** Its `isComplete` only means planning is complete.
- **Results:** always parse JSON. Exit 1 is the only failure exit, so classify by `status[].code`. Treat non-JSON stdout as a provider error that names the argv.

**L4-OSP-002.**
- Change it to: verify `root.source == "nearest"` **and** `realpath(root.path) == realpath(<repo root>)`. That is the directory containing `openspec/`, **not** `openspec/` itself.
- Add: a `source` of `global_default`, `declared` or `store`, or any `store_id` key, is a provider error.

**SCN-DET-08.**
- Change the *Given* to: "the repo has no `openspec/` (or an empty one), inside a directory that has a full OpenSpec root". The current premise (an inner `openspec/` without `config.yaml`) does not trigger the walk-up when `changes/` or `specs/` exist.
- *Then*: `root.path` differs from the repo and SPEC-003 fails.
- **Add SCN-DET-11:** a runner user with a global `defaultStore`, with XDG isolated, makes the provider see `no_openspec_root`, never the other repo.

**L4-OSP-003.** Confirmed. Add three points.
- (a) The `--json` success output does **not** report incomplete tasks, so the harness's own done gate is the only barrier.
- (b) After `archive`, run `validate <cap> --type spec --strict --json` for every capability in the unit's `show` → `deltas[].spec`.
  - Do not use `--all` here: an unrelated invalid change elsewhere in the repo would then fail the unit.
  - This catches strict-only failures in rebuilt main specs: the placeholder Purpose (recorded, exit 1) and missing SHALL.
  - On failure, restore the worktree and go to `escalated`, as L4-ARC-001 already says for archive errors.
- (c) Mapping:
  - `archive_validation_failed`, `archive_spec_update_failed` and `archive_target_exists` → `escalated`, with the code in the event.
  - `archive_change_not_found` → a state bug.

**L4-OSP-006.** Confirmed. Exact rule: any `validate` issue whose message starts with `Archive would refuse this delta:` counts as an ERROR. At archive time the same problem shows up as `archive_spec_update_failed` ("No files were changed.").

**New L4-OSP-007 (Purpose for new capabilities).**
- At intake, every delta `specs/<cap>/spec.md` whose `<cap>` is not already in `openspec/specs/` MUST contain `## Purpose` of at least 50 characters.
- If not, reject the unit: exit 14, with a `unit.rejected` reason.
- Reason: the CLI does not check this, and archive writes a `TBD` Purpose that fails strict validation.

**L4-OSP-004, L4-TMW-001, SPEC-006 (task grammar).**
- **Parser:**
  - Use the exact port below, with `split('\n')` (never `splitlines()`), the JS whitespace class (including U+FEFF and NBSP), `.` excluding `\n\r\u2028\u2029`, ASCII digits, and JS trim.
  - Golden tests come from the recorded `apply-task-grammar*.json`.
- **SPEC-006 parity:**
  - Compare the harness's `(total, complete)` with `progress`, which includes checkboxes that have no text.
  - Compare per-line `(line, done, description)` with `tasks[]`, which excludes them.
- **Task identity:**
  - Take the id from the description's leading dotted number, using OpenSpec's own `^(\d+(?:\.\d+)+(?:[A-Za-z]+)?)(?=\s|$)` from `task-numbering.js`.
  - If there is no number, use `L<line>`.
  - Never use the CLI `id`.
- **Marker writes:** write markers only where the bracket is exactly `[ ]`. The offset is `index('[') + 1`, and the write is `' '` → `'x'`. Never use the start of regex group 1.
- **Intake lint:**
  - Flag any other unchecked form (`[]`, `[  ]`, `[ ](…)`) as SPEC-006a, a doctor error. Under `sdd.enforce`, the unit is rejected.
  - `[-]` and `[~]` count as not done.
  - `[ ]*` is a **required** task in OpenSpec.
  - Checkboxes inside code fences or HTML comments count, so SPEC-004 should warn about them: they block `all_done`.
- **Parents:** OpenSpec has no optional tasks and no parent/leaf meaning, and parent checkboxes count in `progress`. The harness MUST tick a parent when its last child is ticked, or `remaining` never reaches 0.

**L4-IMP-001.** For OpenSpec, the next task is the first pending checkbox, in document order, that has no pending indented checkbox children. Drop "non-optional" for OpenSpec.

**L4-OSP-005.** Confirmed. Add:
- After `new change <p>-fix-<n> --json`, append `skip_specs: true`.
- The harness MUST also write a `proposal.md`, because `show_error` happens without one.
- `tasks.md` numbering MUST keep `N.M` under `## N.`. A mismatched or duplicate number is a WARNING, which fails strict validation.
- Note: `new change` writes only `.openspec.yaml`.

**L4-SPI-001 `unit_dir()`, §12 and L4-ARC-003.**
- `archive` moves the **whole** change folder, including `questions.md`, `verification.md`, `.l4/` and evidence, to `openspec/changes/archive/YYYY-MM-DD-<id>/`.
- `unit_dir()` for an archived unit MUST resolve there.
- The ledger, criteria and lessons must never hard-code `openspec/changes/<id>/` after archiving.
- Get archived names from `list --all --json` (`archived:true`).

**ENV-003 and runner provisioning (#12).**
- Check `<resolved node> --version` ≥ 20.19.0 for the **same** node path the provider will run, and check that the prefix `--version` equals the pin.
- Save the absolute node path (config `spec.openspec.node` or the `$L4_CACHE` tool manifest), because nvm's node is not on a shell-executor's PATH.

**SCN-SEC-08.** Passes as written. Add the assertion that a bare `openspec` resolved from PATH is never executed: with `./node_modules/.bin` first on PATH, the planted code ran.

**Adapter call table** (`src/l4/specs/openspec.py`):
```
argv = [node, f"{prefix}/node_modules/@fission-ai/openspec/bin/openspec.js", *args]
env  = {PATH, HOME, TZ="UTC", DO_NOT_TRACK="1", OPENSPEC_TELEMETRY="0", OPENSPEC_NO_UPDATE_CHECK="1", NO_COLOR="1",
        XDG_CONFIG_HOME=f"{cache}/openspec-xdg/config", XDG_DATA_HOME=f"{cache}/openspec-xdg/data"}
run(argv, cwd=realpath(repo), env=env, stdin=DEVNULL, capture_output=True, timeout=60)
list_units : list --json --sort name [--all]
load       : show <id> --type change --json ; show <cap> --type spec --json
validate   : validate <id> --strict --json  (+ "Archive would refuse this delta:" INFO => error) + L4-OSP-007 Purpose check
tasks      : instructions apply --change <id> --json  (+ own exact parse; SPEC-006 parity)
create_fix : new change <p>-fix-<n> --json ; append skip_specs ; write proposal.md + tasks.md
archive    : own done_gate + validate <id> --strict ; archive <id> --yes --json ; validate <cap> --type spec --strict --json per touched cap
doctor     : validate --all --strict --json ; root check on every result
```

**Exact Python port** of the OpenSpec 1.14.0 task parser. It matched the CLI on every recorded case:
```python
import re
JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
JS_WS_CHARS = JS_WS.replace("\u2000-\u200a", "".join(chr(c) for c in range(0x2000, 0x200B)))
S = f"[{JS_WS}]"
DOT = "[^\n\r\u2028\u2029]"
EXACT = re.compile(
    rf"^{S}*(?:[-*+]|[0-9]{{1,9}}[.)]){S}*\[(?:{S}*([^\]{JS_WS}]?){S}*\](?![(\[])|{S}+\]){S}*({DOT}*)")

def parse(content: str):
    out = []
    for i, line in enumerate(content.split("\n"), 1):          # never splitlines()
        m = EXACT.match(line)
        if m:
            out.append({"done": (m.group(1) or "").lower() == "x",
                        "description": m.group(2).strip(JS_WS_CHARS), "line": i})
    return out

def apply_view(content: str):                                   # == instructions apply --json
    parsed = parse(content)
    tasks = [t for t in parsed if t["description"]]
    done = sum(t["done"] for t in parsed)
    return {"progress": {"total": len(parsed), "complete": done, "remaining": len(parsed) - done},
            "tasks": [{"id": str(i + 1), **t} for i, t in enumerate(tasks)]}
```

## Recorded fixtures (paths)

All under `/Users/USER/src/l4/tests/fixtures/recorded/openspec/1.14.0/`:

- **`_index.jsonl`:** one line per CLI case: argv, exit, ms, whether stdout is JSON, whether stderr was non-empty, and the stdout file name.
- **CLI stdout** (`<case>.json` or `.txt`, plus `<case>.stderr.txt` when stderr was not empty):
  - `list`, `list-sort-name`, `list-specs`
  - `show-add-farewell`, `show-add-farewell-type-change-deltas-only`, `show-broken-change`, `show-chore-tasks-only`, `show-greeting-spec`, `show-unknown`, `show-fix-unit-skip-specs`
  - `validate-{add-farewell,broken-change,chore-tasks-only,with-extras,no-purpose,modify-missing,no-shall,task-grammar}-strict`, `validate-no-shall-nonstrict`, `validate-all-strict`, `validate-unknown`, `validate-noarg`, `validate-new-change-empty-strict`, `validate-fix-unit-skip-specs-strict`
  - `status-add-farewell`, `status-chore-tasks-only`, `status-unknown`
  - `apply-{add-farewell,chore-tasks-only,with-extras,broken-change,task-grammar,task-grammar-crlf,unknown}`, `apply-new-empty-change`, `apply-fix-unit-skip-specs`
  - `archive-{with-extras-yes,with-extras-yes-json,add-farewell-yes,add-farewell-yes-json,add-farewell-json-noyes,add-farewell-noyes-text,broken-change-yes,broken-change-yes-json,chore-tasks-only-yes-json,no-purpose-yes-json,modify-missing-yes-json,no-shall-yes-json,unknown-yes-json,target-exists-yes-json}`
  - `post-archive-{list-all,list-archived,list-specs,validate-archived,no-purpose-validate-specs-strict,no-purpose-validate-notify-spec-strict,no-purpose-show-notify,no-shall-validate-specs-strict,add-farewell-validate-all-strict,add-farewell-validate-archived,add-farewell-validate-greeting-spec-strict}`
  - `new-change-json`, `new-change-exists-json`, `new-change-badname-json`
- **Repo state after archive:**
  - `archive-<case>.gitstatus.txt` for 10 cases
  - `archive-add-farewell-yes-json.specs-after.md`
  - `archive-no-purpose-yes-json.specs-after.md`
  - `archive-with-extras-yes-json.specs-after.md` (this one also lists every file under `changes/archive/`)
- **Experiments:**
  - `root-resolution.txt`
  - `global-default-store.txt`
  - `prefix-and-node-resolution.txt`
  - `prompt-stdin-behaviour.txt`
  - `timings.txt`
  - `task-parser-parity.txt`

`setup.sh` above recreates the fixture inputs byte-for-byte. The scratch scripts (`setup.sh`, `record.sh`, `osrun.py`, `osp_tasks.py`, `compare.py`, `misc.py`, `ancestor.sh`, `storetest.sh`) are in `/tmp/scratch/spikes/openspec-contract/`.