Every group is one implementer step, run in order in one worktree. Each step follows these rules:
- Read `proposal.md`, `design.md` and `specs/opencode-v2-current/spec.md` of this change. Read L4-OCV-001 to
  L4-OCV-019 and SCN-OCV-01 to SCN-OCV-48 in `docs/SPEC.md`, which this change's spec commit already holds. Also read
  `openspec/changes/opencode-v2/design.md` (D5, D7, D13 and the amendment E1 to E9), which this change builds on.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>` and `.venv/bin/ruff format --check <changed files>`. Never run the whole suite
  in a task: the orchestrator runs it once at the end.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages are `opencode-v2-current <n>: …`,
  with no trailer and no local path.
- Never start an `opencode` or `opencode2` binary, and never reach the network. Tests use the recorded fixtures and
  fake runners only. Never write a `while pgrep …` loop or any loop that waits on a process name.
- Name no consumer repository. Write "a consumer repository" when one is meant.
- v1 is unchanged. `tests/unit/agents/test_opencode.py`, `test_factory_opencode_major.py` (except the SCN-OCV-26 test,
  task 6) and the other v1 tests pass without edits.
- Do not write a parser for a shape no fixture holds. The rows that stay [U] keep their fallbacks (design D9).

## 1. Fixtures (design D8)

- [x] 1.1 The orchestrator passes the raw directories of the live check as `OC2_MAC` (the macOS runs) and `OC2_BOX`
  (the container runs). Write a throwaway scrub script outside the repository. It applies the rules of design D8, in
  this order:
  1. every path that starts with the absolute path of `$OC2_MAC` (also its twin with or without the `/private` prefix)
     becomes `/tmp/l4-oc2` plus the rest of the path;
  2. a remaining `/private/tmp/` prefix, or a `/tmp/` prefix other than `/tmp/l4-oc2`, that a model shortened with `…`
     becomes `/tmp/l4-oc2/`;
  3. `/home/runner` becomes `/tmp/l4-oc2box`, and a path that starts with `/out/` (preceded by a quote, a space or
     nothing) becomes `/tmp/l4-oc2box/out/`;
  4. each distinct `ses_[A-Za-z0-9]+` id becomes `ses_l4live<n>`, numbered per run, the same in a stream and its
     export;
  5. any remaining occurrence of the recording user's login (`$USER` of the orchestrator, passed as `OC2_LOGIN`)
     becomes `user`.

  The script reads each file as text, applies the rules and writes JSON unchanged otherwise. Check that every line of a
  `.jsonl` and every `.export.json` still parses as JSON. Copy each pair to
  `tests/fixtures/recorded/opencode/2.2.6/`:

  | Source (`step/events.jsonl`, `step/events.export.json` of the run) | Target |
  |---|---|
  | `$OC2_BOX/judge-1` | `live-judge.jsonl`, `live-judge.export.json` |
  | `$OC2_BOX/judge-4` | `live-judge-free.jsonl`, `live-judge-free.export.json` |
  | `$OC2_BOX/implement-3` | `live-implement.jsonl`, `live-implement.export.json` |
  | `$OC2_MAC/bounded-1` | `live-bounded.jsonl`, `live-bounded.export.json` |
  | `$OC2_MAC/tools-1` | `live-tools-permission.jsonl`, `live-tools-permission.export.json` |
  | `$OC2_BOX/daemon-2` | `live-cli-denied.jsonl`, `live-cli-denied.export.json` |
  | `$OC2_BOX/daemon-1` | `live-cli-disturbed.jsonl`, `live-cli-disturbed.export.json` |
  | `$OC2_BOX/judge-2` | `live-error-no-route.jsonl`, `live-error-no-route.export.json` |

  Also write `live-version.stdout.txt` with the one line `opencode v2.2.6`, the output of `opencode2 --version` on both
  machines.
- [x] 1.2 Write `tests/fixtures/recorded/opencode/2.2.6/README.md` in the manner of the 2.0.32 README. Its header says
  each file was recorded on 2026-11-10 with `@opencode/cli` 2.2.6, by L4 0.4.55's `OpenCodeV2Adapter.run` with the real
  binary. "box" means a Linux arm64 container with L4's bubblewrap sandbox and an agent spec built like
  `Workbench.agent_spec`. "mac" means macOS arm64 with no sandbox, an isolated HOME and isolated XDG directories. The
  models are `opencode-go/deepseek-v4.1-flash` (a paid key through the credential loader) and `opencode/…-free` (no
  login). The header also states the scrub rules of 1.1.

  Then write one line per file: the machine, the mode, the model, the configuration (0.4.55's, or with the allow-list,
  the CLI denies and the private data home of this change), what it shows (design D8), and the D9 row it records. Add
  one line saying that the probe's hello was checked live (paid and free, mac and box) but its raw stream was not kept,
  so the hello has no fixture.
- [x] 1.3 Run, over `tests/fixtures/recorded/opencode/2.2.6/`:
  - `grep -rnE '/private/|/Users/|/home/[a-z]|/var/folders/'`, and a grep for the absolute paths of `$OC2_MAC` and
    `$OC2_BOX`;
  - `grep -rni "$OC2_LOGIN"`;
  - `grep -rnE 'sk-[A-Za-z0-9]{8}|API_KEY=|apiKey'`.

  Each must print nothing. Then run `.venv/bin/python -m l4.recordedversions --write`.
  `src/l4/recorded_versions.json` must list `2.0.32` and `2.2.6` under `opencode`. Commit the fixtures, the README and
  the regenerated JSON.

  Done when: the 17 fixture files and the README are there, the three greps print nothing, and
  `tests/unit/test_recorded_versions.py` passes.

## 2. The pin 2.2.6 (L4-OCV-019, L4-OCV-002; SCN-OCV-02, SCN-OCV-04, SCN-OCV-43; design D1)

- [x] 2.1 Tests first:
  - `tests/unit/provision/test_catalog.py`: `OPENCODE2_VERSION == "2.2.6"`. `catalog_pins()["agent:opencode2"] ==
    "2.2.6"`. The manual command for the `opencode2` tool names `@opencode/cli@2.2.6`.
  - `tests/unit/provision/test_install.py` and `test_plan.py`: the planned install runs `npm install --prefix
    <l4_home>/npm-opencode2 … --save-exact @opencode/cli@2.2.6`.
  - `tests/unit/runner/test_prereqs_steps.py`: `OPENCODE2_VERSION=${OPENCODE2_VERSION:-2.2.6}` is in the top block, and
    `check_opencode2` with a stub that prints `opencode v2.2.6` returns 0.
  - `tests/unit/test_recorded_versions_major.py` (SCN-OCV-24 as amended): `unrecorded("opencode", "2.0.33")` is
    `["2.0.32", "2.2.6"]`; `unrecorded("opencode", "2.2.6")` is None.
  - `tests/unit/doctor/test_live_005.py` (SCN-OCV-43): `opencode v2.2.6` gives no warning for a v2 profile, and
    `opencode v2.2.7` warns `unrecorded version` naming `2.0.32, 2.2.6`.
  - `tests/unit/availability/test_probes_opencode_v2.py` (SCN-OCV-02): the binary reason holds
    `install @opencode/cli@2.2.6`.
  - `tests/unit/docs/test_pin_clis_docs.py`: the PRQ-20 row holds `2.2.6`.
- [x] 2.2 Code:
  - `src/l4/provision/catalog.py`: `OPENCODE2_VERSION = "2.2.6"`. The comment above it names
    `tests/fixtures/recorded/opencode/2.2.6`.
  - `scripts/runner/prereqs.sh`: the default and the comments that name `opencode v2.0.32` as the pinned form.
  - `docs/runner/README.md`: the PRQ-20 row names `2.2.6` and loses "experimental and not yet checked against a live run".
  - `src/l4/agents/opencode_v2.py`: the module docstring names `2.2.6`.
- [x] 2.3 Then `git grep -n "2\.0\.32" -- src scripts tests/unit docs/runner`. Change each place where 2.0.32 stands for
  the pin, or for the version `l4 doctor --fix` installs. Prefer `OPENCODE2_VERSION` in tests. Leave each place where it
  stands for a 2.0.32 recording or for an arbitrary v2 version that the v1 gate refuses (`opencode v2.0.32` as the v2
  found as `opencode`). Run `tests/unit/provision tests/unit/runner tests/unit/doctor tests/unit/config tests/unit/test_recorded_versions.py tests/unit/test_recorded_versions_major.py tests/unit/test_versions_major.py tests/unit/availability tests/unit/docs/test_pin_clis_docs.py tests/unit/eval/test_env.py tests/unit/yolo/test_yolo_preflight_script.py`
  and the ruff checks. Commit.

  Done when: these pass, and every remaining `2.0.32` in `src`, `scripts` and `tests/unit` names a recording or an
  arbitrary v2 version.

## 3. The allow-list (L4-OCV-015, L4-OCV-005; SCN-OCV-09, SCN-OCV-29 to SCN-OCV-31; design D2)

- [x] 3.1 Tests first, new `tests/unit/agents/test_opencode_v2_allow_list.py`. Give it a small evaluator: the last rule
  whose `action` matches the call's action and whose `resource` matches its resource (`fnmatch.fnmatchcase` on both)
  decides. The evaluator lives in the test, not in `src`.
  - SCN-OCV-29: `config_content_v2(PermissionPolicy("implement"), Path("/tmp/l4-step/result"), PAID)` has
    `permissions[0] == {"action": "*", "resource": "*", "effect": "deny"}`, and for `opencode/big-pickle` `"ask"`.
    `permissions[1:]`, with the three OpenCode CLI rules of task 4 left out, equals the 0.4.55 array. Pin it as a
    literal taken from the current code before editing.
  - SCN-OCV-30: for each action of the scenario on `calc.py`, the only matching rule is the first, so the effect is
    `deny`. `edit`, `read`, `glob` and `grep` on `calc.py`, and `shell` running `ls`, end at `allow`.
  - SCN-OCV-31: `options.tools: [read, edit]`, the paid judge and the free judge give exactly their 0.4.55 arrays,
    pinned as literals.
  - Edit SCN-OCV-09's test in `tests/unit/agents/test_opencode_v2_command.py` to the amended scenario: the implement
    array is the recorded normalisation with `*:* deny` before it, the CLI denies after its git denies (task 4), and
    `skill` and `subagent` at the end.
- [x] 3.2 Code: in `src/l4/agents/opencode_v2.py` `_permissions`, the implement branch without `options.tools` starts
  with `_rule("*", refuse)`. Add a comment at it: the allow-list of L4-OCV-015, and the two tools that stay offered
  (`worktree_remove`, gated by `edit`; `skill`, offered in every mode). Run `tests/unit/agents/test_opencode_v2_allow_list.py
  tests/unit/agents/test_opencode_v2_command.py tests/unit/agents/test_opencode_v2_run.py
  tests/unit/availability/test_probes_opencode_v2.py` and the ruff checks. Commit.

## 4. The OpenCode CLI denies (L4-OCV-016; SCN-OCV-33, SCN-OCV-34; design D3)

- [x] 4.1 Tests first, new `tests/unit/agents/test_opencode_v2_cli_deny.py`. Give it an evaluator for `shell` rules: the
  last rule with `action == "shell"` whose `resource` matches the command (`fnmatch.fnmatchcase`, `*` spanning any text)
  decides.
  - SCN-OCV-33: the default implement array and `options.tools: [bash, read]` both hold `shell:opencode* deny`,
    `shell:opencode2* deny` and `shell:*bin/opencode* deny`, right after the last git deny. The scenario's four CLI
    commands end at `deny`. Its three ordinary commands end at `allow`.
  - SCN-OCV-34: `options.tools: [read, edit]` and both judge arrays hold no rule whose resource contains `opencode`.
    The v1 `config_content` of an implementer equals its 0.4.55 literal (already pinned by
    `test_factory_opencode_major.py`: assert it is unchanged, do not copy it).
- [x] 4.2 Code: in `src/l4/agents/opencode_v2.py`, add `OPENCODE_CLI = ("opencode*", "opencode2*", "*bin/opencode*")`
  beside the import of `GIT_WRITES`. Add its denies right after the git denies, under the same `if "shell" in actions`.
  Add a comment: it is a guard, the sandbox is the boundary, and the pattern is `*bin/opencode*`. It is not
  `*/opencode*`, which would refuse any command naming a source path that holds `/opencode`. It is not
  `*/bin/opencode*`, which misses npm's `.bin` (design D3). `src/l4/agents/opencode.py` is not touched. Run the 3.2 files plus the new one, and
  `tests/unit/agents/test_opencode.py tests/unit/agents/test_factory_opencode_major.py`, and the ruff checks. Commit.

## 5. The private data home (L4-OCV-017, L4-OCV-003; SCN-OCV-06, SCN-OCV-37 to SCN-OCV-39; design D4)

- [x] 5.1 Tests first:
  - New `tests/unit/agents/test_credentials_no_stored_login.py`: `no_stored_login` is True for `cli_major: 2` with
    `auth: api_key` on `opencode-go/x` and on `opencode/x`, and for `cli_major: 2` on `opencode/x` with no `auth`. It is
    False for `cli_major: 2` on `opencode-go/x` with no `auth` or `auth: subscription`, for `openrouter/x`, for every
    `cli_major: 1` profile (`auth: api_key` included) and for every other adapter.
  - `tests/unit/agents/test_opencode_v2_run.py`:
    - SCN-OCV-37, with the `V2Proc` fake. The fake run writes a file into `XDG_DATA_HOME`, and the fake export records
      whether it is still there. A symlink planted at `<step dir>/opencode2-data` is removed and its target is untouched.
      `UV_PYTHON_INSTALL_DIR` and `UV_TOOL_DIR` equal what the shared helper (5.2) gives for the request's `host_env`.
    - SCN-OCV-38, for `profile(PAID)` and `profile("openrouter/x")`.
    - Split `test_run_and_export_each_have_an_empty_state_directory_of_their_own_and_no_data_directory`: it keeps its
      assertions for `profile(PAID)`, a stored login. The default `profile()` (`opencode/big-pickle`) moves to SCN-OCV-37.
  - `tests/unit/availability/test_probes_opencode_v2.py`: SCN-OCV-39 (the hello's `data` directory existed empty and
    0700 when the hello started and is gone after it; the auth step of both profiles starts no process: the `SpyRun`
    records no `auth list`) and SCN-OCV-38's hello and auth part. The existing `"XDG_DATA_HOME" not in env` assertions
    for `GO` stay.
  - `tests/unit/agents/test_opencode_v2_command.py`: `isolation_env_v2` with no data directory still sets no
    `XDG_DATA_HOME`. With one, it sets it and the two uv variables.
  - `tests/unit/sandbox/test_bwrap_home.py` (or the file that tests `spec_paths`): the uv directories `spec_paths`
    binds equal what the shared helper returns for the same host environment.
- [x] 5.2 Code:
  - `src/l4/agents/credentials.py`: `no_stored_login(profile)` (design D4). It must not import `l4.agents.opencode`;
    `"opencode/"` is `OPENCODE_OWN_PREFIXES[0]`.
  - `src/l4/sandbox/home.py`: one helper, `uv_dirs(host_env, home) -> dict[str, str]`, which returns
    `{"UV_PYTHON_INSTALL_DIR": …, "UV_TOOL_DIR": …}` by the rule `derive_tool_paths` uses today. `derive_tool_paths`
    then uses it.
  - `src/l4/agents/opencode_v2.py`:
    - `DATA_DIR = "opencode2-data"`.
    - `isolation_env_v2(config_dir, state_dir, content, *, data_dir=None, extra=None)`: `XDG_DATA_HOME` and `extra`
      only when given.
    - `run()`: for a profile that needs no stored login, `_fresh_dir(step_dir / DATA_DIR)` before the run. The run's
      and the export's environments get it and `uv_dirs(req.host_env, home)`, where `home` is the host's `HOME`, as
      `spec_paths` takes it.
    - `_hello_v2_once`: an empty 0700 `data` directory in the scratch directory, for such a profile.
    - Comments at each branch name L4-OCV-017.
  - Run `tests/unit/agents/test_opencode_v2_run.py tests/unit/agents/test_opencode_v2_command.py
    tests/unit/agents/test_credentials_no_stored_login.py tests/unit/availability/test_probes_opencode_v2.py
    tests/unit/sandbox` and the ruff checks. Commit.

## 6. The sandbox does not bind the real data and config homes (L4-OCV-018; SCN-OCV-40 to SCN-OCV-42; design D5)

- [x] 6.1 Tests first, new `tests/unit/sandbox/test_bwrap_own_homes.py`, on the `make_spec` fixture of
  `tests/unit/sandbox/conftest.py` (extend it with `~/.config/opencode` and `~/.cache/opencode` if it lacks them):
  - SCN-OCV-40: with `hide_own_homes=True` and `adapter="opencode"`, the argv has `--tmpfs <home>/.local/share/opencode`
    and `--tmpfs <home>/.config/opencode`, no `--bind` of either, and `--bind` of `<home>/.cache/opencode`.
  - SCN-OCV-42: with the configured paths of the scenario, `auth.json` is `--ro-bind /dev/null <path>` and not bound,
    `/opt/oc-login` is under a tmpfs and not bound, and the cache home is bound.
  - SCN-OCV-41: `tests/unit/implementer/test_workbench.py` (or a new `test_workbench_own_homes.py` beside it). For the
    three profiles of the scenario, `wb.agent_spec().hide_own_homes` is False, and the bwrap argv equals, as a list, the
    argv of `dataclasses.replace(spec, hide_own_homes=False)`. For a `cli_major: 2` api-key profile it is True. The same
    for the readiness review's spec (`tests/unit/yolo/test_yolo_readiness_review.py` or a new file beside it).
  - `tests/unit/sandbox/test_probe_parity.py` passes unchanged.
- [x] 6.2 Code:
  - `src/l4/sandbox/base.py`: `SandboxSpec.hide_own_homes: bool = field(default=False, kw_only=True)`;
    `OWN_KEPT_HOMES = {"opencode": ("~/.cache/opencode",)}`; `own_login_binds(spec)`; and
    `hidden_credential_paths` adds the dropped paths. A path is kept only when it is at or below an
    `OWN_KEPT_HOMES` entry expanded against `spec.home` (review fix; the first version dropped only paths related to the
    data and config homes).
  - `src/l4/sandbox/bwrap.py`: the bind loop binds `own_login_binds(spec)`, and the `NO_LOGIN_BIND` rule stays.
  - `src/l4/implementer/workbench.py` `agent_spec` and `src/l4/yolo/readiness.py` `_Calls.__init__`:
    `hide_own_homes=no_stored_login(<selected profile>)`.
  - Leave the docstrings of `bwrap.py` and `base.py` saying what is bound. `scripts/runner/sandbox-probe.sh` is not
    changed: it builds no profile.
  - Run `tests/unit/sandbox tests/unit/implementer/test_workbench.py tests/unit/yolo` (the readiness files) and the
    ruff checks. Commit.

## 7. Supported, not experimental (L4-OCV-019, L4-OCV-001, L4-OCG-002; SCN-OCV-26; design D6)

- [x] 7.1 Tests first:
  - `tests/unit/agents/test_factory_opencode_major.py`: the SCN-OCV-26 test becomes "a v2 profile selected twice
    records no `agent.experimental`". The v1 test beside it stays.
  - `tests/unit/agents/test_opencode_v2_command.py`: `test_the_adapter_is_the_experimental_opencode` becomes
    `getattr(OpenCodeV2Adapter, "experimental", False) is False` and `name == "opencode"`.
  - The four tests that pin the v1 gate reason (`tests/unit/test_versions_major.py`,
    `tests/unit/provision/test_catalog.py`, `tests/unit/availability/test_probes_opencode.py`,
    `tests/unit/doctor/test_checks_env_004.py`): the reason ends `or set options.cli_major: 2 to run OpenCode 2`.
    Use `git grep -n "OpenCode 2 (experimental)" -- tests src` to find every place.
- [x] 7.2 Code: remove `experimental` from `OpenCodeV2Adapter` and the word from its docstring.
  `catalog.MAJOR_WORDS["opencode"]` loses ` (experimental)`. Run the 7.1 files, `tests/unit/agents tests/unit/doctor
  tests/unit/yolo/test_yolo_preflight_script.py` and the ruff checks. Commit.

## 8. The live fixtures in the parser tests (L4-OCV-006 to -009, -013, -016, -019; SCN-OCV-32, -35, -36, -44 to -47; design D9)

- [x] 8.1 Tests, new `tests/unit/agents/test_opencode_v2_live.py`, from `tests/fixtures/recorded/opencode/2.2.6/`. A
  judge parse uses the judge schema of `tests/unit/agents/test_opencode_v2_parse.py`. An implementer parse uses
  `FILE_RESULT_SCHEMA` and a result text `{"status": "done", "summary": "…"}`. The exact values below were obtained by
  running the 0.4.55 parser on the raw files:
  - SCN-OCV-32: `live-judge`, `live-judge-free` (bound 3) and `live-implement` (bound 200) are `ok` with no denial. Their
    usage (input, output, cached input, cost, peak) is (756, 44, 0, 0.0, 756), (1247, 43, 128, 0.0, 1375) and (2773,
    278, 7936, 0.0, 2851).
  - SCN-OCV-35: `live-cli-denied` is `ok`, and `permission_denials == [{"tool_name": "shell", "tool_input":
    {"command": "opencode2 api GET /api/project"}}]`.
  - SCN-OCV-36 (`export_decides`, U5 [V]): `live-cli-disturbed` with its export is `ok`. With `export=None` it is `error`
    `opencode2 session export failed (no export) and the stream has no final stop`. Name the test
    `test_export_decides_on_the_recorded_disturbed_run`.
  - SCN-OCV-44 (`not_ok_named`, U7 [V]): `live-bounded` as a judge with `step_bound=2` is `error`
    `step_bound: opencode2 stopped at agents.build.steps 2`, with no denial, although its export says `succeeded`.
  - SCN-OCV-45 (`tools_by_permission`, U2 [V]): `live-tools-permission` is `ok`, with no denial and no `tool_use` whose
    tool is `shell`.
  - SCN-OCV-46 (`sum_messages`, U11 [V]): `usage_from_export` of `live-implement.export.json` and
    `live-cli-disturbed.export.json` equals `info.tokens` (input, output, cache read), with peaks 2851 and 5155. The
    `synthetic` message of the second is not counted.
  - SCN-OCV-47: `live-error-no-route` as a judge, exit code 1, is `error`
    `opencode2 reported an error (provider.no-route), retryable`, with `transient` True and `limit` None.
  - A census test: in all eight streams, a final `step_finish` with reason `stop` is missing only in
    `live-cli-disturbed` and `live-error-no-route`.
- [x] 8.2 Re-point the fallback pin tests named in design D9 (U2, U5, U7, U11): each docstring names its `live-` fixture
  and says the row is [V] on 2.2.6. Rows U1, U3, U4, U6 and U10 keep their pin tests unchanged. Run
  `tests/unit/agents/test_opencode_v2_live.py tests/unit/agents/test_opencode_v2_parse.py` and the ruff checks. Commit.

  Done when: these pass, and no parser in `src` changed in this group.

## 9. Docs (design D1 to D9)

- [x] 9.1 Check the spec commit against the code as built: L4-OCV-015 to L4-OCV-019, the amended L4-OCV-001 to -013,
  L4-OCG-002, L4-SEC-005, the §8.3 v2 row, the L4-FAC-002 v2 table, change-table row 125, and SCN-OCV-29 to SCN-OCV-48
  plus the rewritten SCN-OCV-02, -04, -06, -09, -24 and -26. Check the names, the patterns, the directory names and the
  values. Correct the text where the code had to differ, and say so in the commit message.
- [x] 9.2 `docs/runbook.md` 10.9:
  - The title becomes "OpenCode v2", and the anchors that point at it (7.4, 10.7, the versions paragraph) follow.
  - The "Experimental, and not yet checked against a live run" box becomes a short paragraph: checked live on
    `@opencode/cli` 2.2.6 through L4's probe and run, in a Linux container with L4's sandbox and on macOS; no full L4
    unit has run on v2 yet, so watch the first unit's `verification.md`.
  - The pin moves to 2.2.6 everywhere in the section.
  - The runner-user rule applies to a v2 profile with a stored login only. A profile with `auth: api_key` and
    `OPENCODE_API_KEY`, or an `opencode/` model, has a private data home per step and never opens the runner user's
    `opencode.db`. Name the edge case of a paid `opencode/` model on a stored login (design D4).
  - New bullets: the allow-list and the two tools that stay offered, and the CLI denies (a guard; the sandbox is the
    boundary). Also: a tool other than uv that keeps its data under `XDG_DATA_HOME` sees an empty data home in such a
    step.
  - "What is still open" becomes "Known fallbacks". It lists U1, U3, U4, U6 and U10 with their fallbacks, U8 for a
    stored-login profile, and a line for each recorded row (U2, U5, U7, U9 in part, U11) with its `live-` fixture.
  - The `opencode2 session outcome <value>` note says `succeeded` and `failed` have been seen.
  - Add the note `opencode2 reported an error (provider.no-route), retryable` (a free model with no route; it is
    retried, and a free model's route can come back).
  - Section 11 (known limits) gets one line: no full L4 unit on v2 yet.
  - The pointer in 7.4 drops "(experimental)".
- [x] 9.3 `docs/plan/opencode-v2.md`: §4 and §5 get a status line for 2026-11-10. The live check on 2.2.6 replaced B8 for
  U2, U5, U7, U9 (in part) and U11, B9 was done without a parser change, and the adapter is supported (change
  `opencode-v2-current`). The rows of design D9 that stay open are named. Leave the matrix's 2.0.32 facts as they are,
  because they are history.
- [x] 9.4 `openspec/changes/opencode-v2/tasks.md`: under the headers of groups 8 and 9, add one line each: "Replaced in
  part by `opencode-v2-current` (0.4.56): see its design D7." Leave their boxes unchecked.
- [x] 9.5 `CHANGELOG.md`: check the Unreleased lines of the spec commit against the code as built.
- [x] 9.6 Run `.venv/bin/python scripts/check_spec.py docs/SPEC.md` (exit 0), `.venv/bin/python -m pytest -q -p
  no:cacheprovider tests/unit/docs` and `openspec validate opencode-v2-current --strict`. Commit.

## 10. Final check (orchestrator)

- [ ] 10.1 Run the agents, availability, sandbox, provision, doctor, runner, config and docs unit directories, then
  the whole unit suite once (on this machine at most two full runs at a time). Then run `rg -n "experimental"
  src/l4/agents/opencode_v2.py src/l4/provision/catalog.py`, which must print nothing. Then run `git grep -n
  "2\.0\.32" -- src scripts`, which must show only comments and docstrings that name a 2.0.32 recording or use
  `opencode v2.0.32` as an example of a v2 version string, never the pin.
