Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. D1 to D19 are the rules; §5 "Contracts (texts, exact)"
  holds every text, constant, argv and signature; §2 holds the facts with their labels; §5.6 lists the files. Do not
  change a contract without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and `.venv/bin/mypy <changed
  src files>`. A task that edits `docs/SPEC.md` also runs `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, and
  the output must be clean.
- Work only in this branch's worktree, with its own `.venv`. Never change git configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `copilot-cli <n>.<m>: …`, with
  no trailer and no local path.
- No task before 8.1 needs a Copilot token, and none uses one. Never set `COPILOT_GITHUB_TOKEN`, `GH_TOKEN` or
  `GITHUB_TOKEN` for a `copilot` process. Never read `~/.copilot`, `~/.config/gh`, a keychain or any credential file.
  Unit tests use the recorded fixtures and recording process runners only; a test that needs a token builds a
  placeholder at run time (`"github_pat_" + "x" * 40`).
- No test touches the network. A `Fetcher` is a fake that serves bytes built in the test (a small `.tar.gz` made with
  `tarfile`, its member a few bytes long), and the digest table is monkeypatched for it. `copilot_platform`'s libc is a
  parameter or a stub, never the host's. Only task 0.1 downloads, and only outside the worktree.
- A fake that stands for `ProcRunner` accepts `on_line` and calls it for every line it writes, and stops at the first
  True (design D7). A fake that ignores `on_line` hides the stop rule.
- Never wait on a process with `while pgrep -f ...` (the pattern matches itself). Never pipe a test run into `tail` in
  an `&&` chain. Run commands in the foreground with a timeout.
- Name a consumer "a consumer repository". Name the owner's test repository "the owner's dummy repository". Put no
  local path in docs or fixtures.
- Base: amaster 0.4.25 plus the spike commit `58f31c40`. Row 66 of SPEC §21 is `replay-restore-confined`, on another
  branch: this change takes row 67 and leaves 66 out.
- Waves (the tasks of one wave touch disjoint files):
  1. 0.1 (orchestrator) and 0.2 in parallel;
  2. 1.1, 1.2, 1.3 and 1.4 in parallel (1.3 reads 0.1's `help-config.txt`, 1.4 reads 0.2's paths);
  3. 2.1 and 2.2 in parallel;
  4. 3.1 and 3.2 in parallel;
  5. 4.1 and 4.3 in parallel;
  6. 4.2;
  7. 5.1;
  8. 6.1 and 6.2 in parallel;
  9. 7.1 (orchestrator);
  10. 8.1 (orchestrator, with the owner's token): the last task.

Test worlds: `tests/unit/agents/test_copilot_cli.py` (new; its `FakeProc` records argv, env, cwd and stdin, and calls
`on_line`), the streams of `tests/fixtures/recorded/copilot-cli/1.0.102-byok/`, `tests/unit/agents/test_activity.py`,
`tests/unit/provision/conftest.py` (`FIXTURES`, the install runners), `tests/unit/provision/test_install.py`
(`InstallRunner`), `tests/unit/provision/test_plan.py`, `tests/unit/provision/test_catalog.py`,
`tests/unit/provision/test_human_steps.py`, `tests/unit/runner/test_prereqs_steps.py` (`TEXT`, `pin`, `steps`, the
`as_runner` stub pattern of `_check_opencode`), `tests/unit/availability/` (the `ctx.run` fakes of
`test_probes_kiro.py`), `tests/unit/sandbox/test_bwrap_argv.py`, `tests/unit/verifier/test_selection.py`,
`tests/unit/verifier/test_judge_chain.py`, `tests/unit/delegate/test_independence.py`,
`tests/unit/doctor/test_checks_delegate.py`, `tests/unit/sim/test_happy_kiro_judge.py` (the model for 5.1).

## 0. Evidence and fixtures

- [x] 0.1 Evidence without a token (design F21, F23, F29, F34, F35, D14; L4-PRV-047, L4-PRV-048). Orchestrator, or an
  implementer with Docker. No code. No dependency.
  - In a new scratch directory outside the worktree, download the six tarballs of design §5.4 and `SHA256SUMS.txt`.
    Recompute each sha256 and compare it with §5.4. List each archive whole (`tar -tvzf`): exactly one member
    `copilot`, a regular file of mode 0755 and the size of §5.4.
  - In an `ubuntu:24.04` container of the host's architecture, and of `linux/amd64` if the host runs it (else write
    that x64 waits for task 8.1), with no token, `env -i`, an empty `HOME` and `XDG_CACHE_HOME=/c`: run `copilot
    --version` and list `/c`. If `/c/copilot/pkg/` holds no directory, run `copilot help`, then `copilot -p hi
    --output-format json` (it exits 1 for want of a credential), and list `/c` after each. Record which command
    extracted the package and the layout under `/c/copilot/pkg/`. Then run `copilot --version` with `/c` mounted
    read-only: it must answer. Then the per-run layout of design D14 (F37): `/c` mounted read-only, `XDG_CACHE_HOME=/w`
    (a writable directory) with `/w/copilot/pkg` a symbolic link to `/c/copilot/pkg`; run the command that extracted
    the package: it must answer and write nothing under `/c`. Record what it wrote under `/w`.
  - In the same container, with no token, record: the stdout of `copilot --version`, `copilot help config`, `copilot
    help environment` and `copilot help permissions`, and the standard error and exit code of `copilot -p hi`.
  - On the development Mac, run the darwin binary of the host's architecture once with an empty `HOME` and
    `XDG_CACHE_HOME` set to a scratch directory, never with a token: record whether the package lands there (F35).
  - Write `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/`: `version.stdout.txt`, `help-config.txt`,
    `help-environment.txt`, `help-permissions.txt`, `no-auth.stderr.txt`, `no-auth.exit.txt` and `README.txt` (how
    each was made, the date, no token, not a contract recording). Write `docs/live/copilot-cli/README.md` with a
    section "Evidence without a token" (the URLs, sizes and digests recomputed, the member lists, which command
    extracts, the read-only run, the macOS answer) and index it in `docs/live/README.md`. Delete the downloads.
  - STOP and report to the orchestrator when: a digest or a member differs from §5.4; no command extracts the package
    without a credential (design D14 is amended before task 3.2); the CLI does not run through the `pkg` link of the
    per-run layout (design D14 is amended before task 3.1); `help-config.txt` names no model ids; or
    `--available-tools`, `--allow-tool`, `--add-dir`, `--disallow-temp-dir`, `--session-id`, `--usage-output-file` or
    `--additional-mcp-config` is missing from the help.
- [x] 0.2 Move the BYOK streams (design D17; L4-FAC-022). No dependency.
  - Tests first, `tests/unit/test_recorded_versions.py`: `test_copilot_cli_has_no_recorded_version` (SCN-FAC-48: the
    `generate()` of the fixture tree has no `copilot-cli` key and no `copilot` key).
  - `git mv tests/fixtures/recorded/copilot/1.0.102-byok tests/fixtures/recorded/copilot-cli/1.0.102-byok`. Add
    `README.txt` there: BYOK mode against a local OpenAI-compatible model on 2026-10-22, trimmed as the spike's
    appendix says, not a contract recording of the GitHub-routed CLI. Point `RECORDED` of
    `tests/unit/agents/test_copilot_cli_spike.py` to the new path (2.1 replaces that file).
    `uv run python -m l4.recordedversions --write` must leave `src/l4/recorded_versions.json` unchanged.
  - Run: `tests/unit/test_recorded_versions.py tests/unit/agents/test_copilot_cli_spike.py`.

## 1. Leaf modules

- [x] 1.1 The catalog: the pin, the digests, the platform, the major words (design D13, D15, §5.1, §5.4, §5.5 T18, T19,
  T24; L4-PRV-047, L4-OCG-006). No dependency.
  - Tests first, `tests/unit/provision/test_catalog.py`:
    - `test_copilot_is_pinned_and_in_catalog_pins`: `ADAPTER_PINS["copilot-cli"] == "1.0.102"`,
      `ADAPTER_BINARIES["copilot-cli"] == "copilot"`, `catalog_pins()["agent:copilot-cli"] == "1.0.102"`;
    - `test_the_copilot_digest_table`: the 1.0.102 row equals design §5.4 as literals, six keys, 64 hex digits each;
    - `test_copilot_platform` (SCN-PRV-131): `linux-arm64` with `glibc 2.39` → `linux-arm64`; `linux-x64` with None →
      `linux-x64-musl`; `darwin-arm64` → `darwin-arm64`; `win32-x64` raises `ValueError`;
    - `test_copilot_archive_url`: the three URLs of SCN-PRV-131, and `linux-arm64-musl` →
      `…/v1.0.102/copilot-linuxmusl-arm64.tar.gz`;
    - `test_copilot_major_words` (SCN-OCG-15 text): `major_problem("copilot-cli", "copilot", "GitHub Copilot CLI
      2.0.0.", "1.0.102")` is T18 filled; `GitHub Copilot CLI 1.0.103.` gives None; the plan reason is `found 2.0.0
      (Copilot CLI 2), need copilot 1.x (pinned 1.0.102)`; the OpenCode and Kiro texts are unchanged;
    - `test_manual_command_for_copilot`: T24 on `linux-x64` with a stubbed libc, on `darwin-arm64` with `shasum -a 256
      -c -`, and for a version with no digest;
    - `test_archive_adapters` (`ARCHIVE_ADAPTERS == ("kiro-cli", "copilot-cli")`) and `copilot_unheld_text` (T19).
  - Tests first, `tests/unit/config/test_cli_versions.py`: `{copilot-cli: "2.0.0"}` is a load error with T18b;
    `{copilot-cli: "1.0.103"}` loads; the Kiro and OpenCode load errors keep `(L4-OCG-001, L4-OCG-005)`.
  - Code: `src/l4/provision/catalog.py` (§5.1; `major_config_error` names L4-OCG-006 for `copilot-cli` only). Fix in
    place any existing test that counts four agent pins.
  - Run: `tests/unit/provision tests/unit/config/test_cli_versions.py tests/unit/test_versions.py
    tests/unit/test_versions_major.py`.
- [x] 1.2 The credential, redaction, identity, readiness, the cache path, no login bind (design D12, D14, §5.1, §5.5
  T25; L4-PRV-049, L4-PRV-048). No dependency.
  - Tests first:
    - `tests/unit/agents/test_credentials_copilot.py` (new): `credential_variable("copilot-cli", a)` is
      `COPILOT_GITHUB_TOKEN` for `a` in None, `subscription`, `api_key`; `hosted_login_problem("copilot-cli", a)` is
      None; `credential_loader` with a placeholder token in `host_env` puts the loader in front of the argv and never
      the value into an env dict (SCN-PRV-136).
    - `tests/unit/config/test_redaction.py`: `COPILOT_GITHUB_TOKEN` is in `DEFAULT_REDACT_ENV`, and a line that holds a
      placeholder value is redacted whole (SCN-PRV-136).
    - `tests/unit/availability/test_cooldown.py`: `identity_hash` of a copilot-cli profile changes with
      `COPILOT_GITHUB_TOKEN`.
    - `tests/unit/provision/test_human_steps.py`: SCN-PRV-138 (both auth modes, GitLab and GitHub wording, the unset
      detail).
    - `tests/unit/sandbox/test_bwrap_argv.py`: SCN-PRV-137.
    - `tests/unit/config/test_defaults_copilot.py` (new): `copilot_cache({"L4_HOME": "/x"}) == Path("/x/copilot-cache")`;
      `copilot_env` equals §5.1; `CREDENTIAL_PATHS["copilot-cli"] == ("~/.copilot",)`; `"copilot-cli" not in
      l4.agents.gate.OAUTH_ADAPTERS`.
  - Code: `src/l4/config/defaults.py`, `src/l4/agents/credentials.py`, `src/l4/availability/cooldown.py`,
    `src/l4/provision/readiness.py`, `src/l4/sandbox/base.py` (`NO_LOGIN_BIND`, `hidden_credential_paths`),
    `src/l4/sandbox/bwrap.py` (no bind for an adapter in `NO_LOGIN_BIND`).
  - `tests/unit/config/test_schema.py::test_reference_config_validates_with_placeholder_commit` must still pass (6.1
    adds the `copilot-cli` line to the reference configuration).
  - Run: those files, `tests/unit/sandbox` and `tests/unit/agents/test_login_lock.py`.
- [x] 1.3 The vendor: families, the routed Copilot set, the validator (design D10; L4-FAC-020). Depends on 0.1.
  - Tests first:
    - `tests/unit/availability/test_vendor_copilot.py` (new): `family_vendor("grok-4.1") == "xai"` and
      `family_vendor("mai-code") == "microsoft"`; `is_routed` of copilot-cli with no model, `auto`, `AUTO` or a blank
      model is True, with `claude-sonnet-5.5` False, and kiro-cli's answers are unchanged; `resolve_vendor` of
      `{adapter: copilot-cli, model: claude-sonnet-5.5}` is `("anthropic", "declared")` and of a model of no known
      family keeps `vendor:` (SCN-FAC-42); `COPILOT_ROUTED_DEFAULT`: each id appears in
      `tests/fixtures/recorded/copilot-cli/1.0.102-notoken/help-config.txt`, each id has a known family, its vendors are
      exactly its ids' families, its source is `built-in`; `built_in_routed(name, <copilot-cli on auto>) is
      COPILOT_ROUTED_DEFAULT` and for kiro-cli is `ROUTED_DEFAULT`.
    - `tests/unit/config/test_copilot_vendor.py` (new): SCN-FAC-42's load error text; `vendor: unknown` loads; an `auto`
      profile with `vendor: zhipu` loads.
  - Code: `src/l4/availability/vendor.py` (`MODEL_FAMILIES`, `ROUTED_ADAPTERS`, `COPILOT_ROUTED_DEFAULT` as a literal
    tuple of the ids from `help-config.txt`, `ROUTED_DEFAULTS`, `is_routed`, `built_in_routed`, `resolve_vendor`),
    `src/l4/config/schema.py` (`_vendor_of_the_model` for `ROUTED_ADAPTERS`, its import kept inside the function).
  - STOP and report the id when `help-config.txt` lists a model of no known family. Do not add `unknown` to the set and
    do not invent a family.
  - Run: those files, `tests/unit/availability`, `tests/unit/config` and `tests/unit/verifier/test_selection.py`.
- [x] 1.4 The stream reader (design D9; L4-FAC-019). Depends on 0.2.
  - Tests first, `tests/unit/agents/test_activity.py`: SCN-FAC-41 on the lines of
    `tests/fixtures/recorded/copilot-cli/1.0.102-byok/implement-bash.jsonl`; `tool.execution_start` with no
    `toolCallId` gives `start(None)`; the reader returns a tuple and never raises on 1 MiB of garbage.
  - Code: `src/l4/agents/activity.py` (`copilot_signals`).
  - Run: `tests/unit/agents/test_activity.py`.

## 2. The adapter's parse; PRQ-22

- [x] 2.1 Parse, the stop watcher, usage (design D3 to D8, §5.1, §5.5 T3 to T14; L4-FAC-014 to L4-FAC-019). Depends
  on 0.2.
  - Tests first: replace `tests/unit/agents/test_copilot_cli_spike.py` with `tests/unit/agents/test_copilot_cli.py`
    (delete the spike file and its `test_the_prototype_is_not_registered`; keep the parse tests, adapted to
    `NAME == "copilot-cli"` and the texts of §5.5): SCN-FAC-27, SCN-FAC-28, SCN-FAC-29 (parse part), SCN-FAC-30,
    SCN-FAC-32, SCN-FAC-34, SCN-FAC-35 (both cases, the second from `1.0.102-firstcalls/bad-token.stderr.txt`),
    SCN-FAC-36, SCN-FAC-38, SCN-FAC-39, SCN-FAC-40. Also, on `1.0.102-firstcalls/judge-auto.jsonl` (design F39, F40):
    the judge reply is `L4-OK`, `model_resolved` is `gpt-6-luna`, no tool ran, and the usage file gives the tokens and
    credits of D8; the same stream cut before its `assistant.message` gives `model_resolved` `gpt-6-luna` from
    `session.auto_mode_resolved`; a `(403)` in the bad-token text is `auth` too, and the first line alone is the
    retryable `error` of D6 rule 4. Also: `CopilotStop` returns True
    on the first `model.call_failure` line with `statusCode` 429 of `error-429-retrying.jsonl` (before its
    `assistant.turn_retry` line), and on a `rate_limit` retry line when no 429 failure came before it, and never on any line of `error-500.jsonl`
    (`api_error` retries) or `error-401.jsonl` (`transient_auth_error` retries); a non-JSON line and a JSON array are
    ignored; `parse(..., stop="rate_limit")` gives T8 with the source `copilot.model_call_failure` and no reset time; a usage
    path that is a symbolic link, or a file of 2 MiB, gives zero usage.
  - Code: `src/l4/agents/copilot_cli.py`: `NAME`, the constants of §5.1, `events`, `stream_facts` (with `result_seen`
    and `call_failure_statuses`), `usage_of`, `read_usage(path)` with `l4.fsutil.read_regular_file` (1 MiB),
    `CopilotStop`, and `parse` in the order of D6 and D7. Leave `run` and `probe` as the prototype has them until 3.1
    and 4.1, changing only the names they use.
  - Run: `tests/unit/agents/test_copilot_cli.py tests/unit/agents/test_login_lock_coverage.py`.
- [x] 2.2 PRQ-22 (design D16, §5.4, §5.5; L4-PRV-050, L4-OCG-006). Depends on 1.1.
  - Tests first, `tests/unit/runner/test_prereqs_steps.py`: SCN-PRV-139 (`steps()["PRQ-22"] == ("check_copilot",
    "apply_copilot", "WITH_COPILOT")`; `--with-copilot) WITH_COPILOT=1` in the text; the SKIP line of §5.5; `pin(...)`
    of `COPILOT_VERSION` and the four `COPILOT_SHA256_*` equal `catalog.COPILOT_VERSION` and the catalog's row as
    §5.4 maps them); SCN-PRV-140 (the `as_runner` stub pattern with three versions; in the `apply_copilot` text
    `sha256sum -c` comes before `install -m 755`; no `| sh` and no `| bash`). Extend
    `tests/unit/provision/test_catalog.py::test_catalog_pins_equal_the_defaults_in_prereqs_sh` if it lists the agents.
  - Code: `scripts/runner/prereqs.sh` (the top block, `check_copilot`, an asset helper, `apply_copilot` with the
    warm-up, the `--with-copilot` switch, the step line after PRQ-21), `docs/runner/README.md` (a PRQ-22 row).
  - Run: those files and `bash -n scripts/runner/prereqs.sh`.

## 3. The adapter's run; provisioning

- [x] 3.1 The run: argv, environment, private home, stdin, the stop hook, MCP (design D2 to D5, D7, §5.2, §5.3, T1,
  T2; L4-FAC-013 to L4-FAC-016, L4-FAC-018). Depends on 1.2, 1.4 and 2.1.
  - Tests first, `tests/unit/agents/test_copilot_cli.py`, with the recording `FakeProc`: SCN-FAC-22, SCN-FAC-23,
    SCN-FAC-24 (a placeholder token in `host_env`), SCN-FAC-26, SCN-FAC-29 (the argv part), SCN-FAC-31, SCN-FAC-33. Also:
    the run passes `reader=copilot_signals` and an `on_line` that is a `CopilotStop`; a `FakeProc` that feeds
    `error-429-retrying.jsonl` through `on_line` and stops at True gives `rate_limited` with T8 (the adapter part of
    SCN-FAC-37); the usage file and a leftover result file are removed before the spawn; an `exe` given to the
    constructor skips the PATH lookup; `capabilities()` equals §5.1; `write_run_cache` (SCN-FAC-22's cache part, with
    `L4_HOME` in `host_env` pointing at a temporary directory): a leftover file and a planted `copilot/pkg` directory are
    replaced by the link, which is a symbolic link to `<L4_HOME>/copilot-cache/copilot/pkg` whether or not that target
    exists, and the run's `XDG_CACHE_HOME` is never the L4 cache itself in any mode.
  - Code: `src/l4/agents/copilot_cli.py` (`effective_model`, `write_home`, `write_run_cache`, `gate_rule`,
    `build_command`, `CopilotCliAdapter.__init__(runner, exe)`, `capabilities`, `run`).
  - Run: `tests/unit/agents/test_copilot_cli.py tests/unit/agents/test_judge_cwd.py`.
- [ ] 3.2 Provisioning: the install, the warm-up, the plan rules, the version environment (design D13, D14, §5.5 T19 to
  T24; L4-PRV-047, L4-PRV-048, L4-OCG-006). Depends on 1.1 and 1.2.
  - Tests first:
    - `tests/unit/provision/test_install.py` (`InstallRunner`; a tarball built with `tarfile` in the test; the digest
      table monkeypatched): SCN-PRV-129, SCN-PRV-130, SCN-PRV-132, SCN-PRV-134. The staged file is gone after a success
      and after a failure; an existing `~/.local/bin/copilot` is replaced, and kept when the rename fails.
    - `tests/unit/provision/test_plan.py`: SCN-PRV-133 (both parts), SCN-OCG-16 (CI and person), and a plan on
      `darwin-arm64` that installs (no `manual`).
    - `tests/unit/doctor/test_checks_env.py`: the `--version` read of `copilot` has `copilot_env` (SCN-PRV-135, doctor
      part); the read of `claude` is unchanged.
  - Code: `src/l4/provision/install.py` (`_install_copilot`, the warm-up, `_verified`'s exact check and cache check
    for `ARCHIVE_ADAPTERS`, `_apply`'s digest text for `ARCHIVE_ADAPTERS`, the 403 and 404 text),
    `src/l4/provision/runner.py` (one rule for `ARCHIVE_ADAPTERS` where `_kiro_by_hand` reads `kiro-cli`;
    `installed_version` adds `copilot_env(env)` for copilot-cli), `src/l4/doctor/checks_env.py` (`version_env`). Do
    not add keys to `scrub_env` for other installers.
  - Run: `tests/unit/provision tests/unit/doctor`.

## 4. Probe, independence, registration

- [ ] 4.1 The probe ladder (design D11, §5.5 T15 to T17a; L4-FAC-021, L4-OCG-006). Depends on 3.1.
  - Tests first, `tests/unit/availability/test_probes_copilot.py` (new, with a fake `ctx.run` as in
    `test_probes_kiro.py`): SCN-FAC-45, SCN-FAC-46, SCN-FAC-47, SCN-OCG-15. Also: the `binary` step's environment has
    `copilot_env(ctx.environ)` (SCN-PRV-135, probe part); a hello whose stream holds a `session.error` 401 fails with T6
    and the class `auth`; a hello that started a tool fails with T17 and the class `other`.
  - Code: `src/l4/agents/copilot_cli.py` (`probe_copilot`, `CopilotCliAdapter.probe`), `src/l4/availability/probes.py`
    (`_binary`'s environment for `copilot`).
  - Run: those files and `tests/unit/availability`.
- [ ] 4.3 Independence and the delegate (design D4 masked tree, D10; L4-FAC-020, L4-FAC-015). Depends on 1.3 and 3.1.
  - Tests first:
    - `tests/unit/verifier/test_selection.py`: SCN-FAC-43; `seat_of` for a copilot-cli profile pinned to
      `gpt-6.1-sol` is `JudgeSeat("gpt-6.1-sol", False)` and on `auto` is `JudgeSeat(None, True)`; `Party.text()` of a
      routed copilot-cli party names its vendors.
    - `tests/unit/verifier/test_judge_chain.py`: SCN-FAC-44 at the ladder, with a scripted copilot-cli judge.
    - `tests/unit/delegate/test_independence.py`: a copilot-cli delegate with no model under `independence: model` is
      vetoed with `independence: model: delegate profile <name> is routed (auto)`.
    - `tests/unit/doctor/test_checks_delegate.py`: a copilot-cli delegate profile is accepted; with no model it gets the
      routed problem line, not `has no model`.
    - the test file of `delegate/run.py`'s `_call` (`tests/unit/delegate/test_pass.py` or the one that asserts
      `masked=True` for opencode): a copilot-cli delegate gets the masked tree (SCN-FAC-29, tree part).
  - Code: `src/l4/verifier/selection.py` (`seat_of` reads `is_routed` and `ROUTED_ADAPTERS`, not `== "kiro-cli"`),
    `src/l4/delegate/independence.py` (`DELEGATE_SERVES`, the routed rule), `src/l4/doctor/checks_delegate.py`
    (`ADAPTERS_THAT_SERVE`, the routed rule, the texts that list the adapters), `src/l4/delegate/run.py` (the masked
    tree for copilot-cli).
  - Run: `tests/unit/verifier tests/unit/delegate tests/unit/doctor/test_checks_delegate.py`.
- [ ] 4.2 Registration, the roles and the login lock (design D1, D7 cool-down; L4-FAC-013, L4-FAC-018). Depends on 4.1
  and 4.3.
  - Tests first:
    - `tests/unit/config/test_judge_roles.py` and `tests/unit/llm/test_judge_adapters.py`: the tuples hold
      `copilot-cli` before `fake`; `agent_judge.JUDGE_ADAPTERS is roles.JUDGE_ADAPTERS`; `set(HARNESS_ADAPTERS) ==
      set(ADAPTERS)` (SCN-FAC-25).
    - `tests/unit/yolo/test_yolo_preflight_script.py`: the skill's copies equal the harness's tuples.
    - `tests/unit/init/test_init_cli.py` (or the file that checks `l4 init`'s configuration): no `copilot-cli`
      profile (SCN-FAC-25).
    - `tests/unit/agents/test_login_lock_coverage.py`: `agents/copilot_cli.py` is classified `GATED`; a `copilot-cli`
      profile joins the dynamic run and probe tests (give the request what the adapter needs to reach its spawn).
    - `tests/unit/implementer/test_tdd_red.py`: SCN-FAC-37's chain part, after
      `test_a_throttled_step_is_a_role_limit_that_consumes_no_attempt` (a copilot-cli `rate_limited` result with the
      `copilot.model_call_failure` limit is a role limit and uses no attempt).
    - `tests/unit/availability/test_fallback.py`: that limit cools the profile for `availability.default_cooldown`
      (not Kiro's two minutes).
    - `Factory.routed(name, <copilot-cli on auto>)` returns `COPILOT_ROUTED_DEFAULT` when no probe recorded a set.
  - Code: `src/l4/agents/factory.py` (`ADAPTERS`; `Factory.routed`'s fallback is `built_in_routed`), `src/l4/doctor/checks_config.py` (its routed-set fallback reads `built_in_routed` too, not kiro's `ROUTED_DEFAULT`; a test with a copilot-cli `auto` profile),
    `src/l4/config/roles.py`, `plugins/l4/skills/l4/scripts/yolo_preflight.py`.
  - Run: those files, `tests/unit/agents`, `tests/unit/llm`, `tests/unit/config`, `tests/unit/init` and
    `tests/unit/yolo/test_yolo_preflight_script.py`.

## 5. Simulation

- [ ] 5.1 A Copilot judge replayed through the real adapter (design D18; L4-FAC-014). Depends on 4.2.
  - Tests first: `tests/unit/sim/test_happy_copilot_judge.py` (new, after `test_happy_kiro_judge.py`): the scenario
    ends `in_review` with `verify.verdict PASS`; the replayed argv holds `--model auto` and
    `--available-tools=l4_no_tools`, the stdin is the judge prompt, and the verdict's independence line reads `served
    gpt-6.1-sol`. In the scenario loader's tests: `replay: {adapter: copilot-cli, …}` loads, and an unknown `adapter`
    under `replay` is still an error. The manifest lists `happy-copilot-judge` as ready.
  - Code: `src/l4/sim/scenarios.py` (`JudgeScript.replay.adapter` accepts `copilot-cli`), `src/l4/sim/replay.py` (a
    router per adapter; `CopilotCliAdapter(ReplayProc(stream), exe=REPLAY_EXE)`), `src/l4/sim/runner.py` (the replay
    profile carries its adapter; `sim_adapters` adds the router of each replayed adapter),
    `src/l4/sim/builtin/fixtures/openspec-basic/payloads/judge_pass.copilot.jsonl` (synthetic, in the shape of
    `judge-hello.jsonl`: the last assistant content is a valid verdict for the scenario's criteria,
    `assistant.message.model` is `gpt-6.1-sol`, one `result` event), `src/l4/sim/builtin/scenarios/happy-copilot-judge.yaml`
    (`happy-openspec` with that judge), `src/l4/sim/builtin/manifest.py`.
  - Run: `tests/unit/sim` and `uv run l4 simulate happy-copilot-judge happy-kiro-judge`.

## 6. Docs

- [ ] 6.1 SPEC (design D19). Depends on 1.1 to 5.1.
  - `docs/SPEC.md`:
    - §3.2: the commented profile of design §5.5 (with a model id from `help-config.txt`) and `copilot-cli:
      ["~/.copilot"]` in `sandbox.credential_paths`;
    - §8.3: a `copilot-cli` row (the argv of §5.2, the result and session of D6, prompt contract, no resume, the
      permissions of D3 to D5, MCP of D5 with its labels, the quota signal of D7) and a HB-X1 row per mode;
    - a new §8.3.3 "GitHub Copilot CLI": L4-FAC-013 to L4-FAC-022 as in this change's spec, with the facts of design
      §2.2 and their labels;
    - L4-FAC-011 (copilot-cli reports no peak) and L4-FAC-012 (its reader);
    - L4-PRV-044 (the three switches of D2), L4-PRV-047 to L4-PRV-050 after L4-PRV-046, L4-OCG-006 after L4-OCG-005;
    - ENV-004's major list, §15 PRV-001, L4-DLG-015 (five adapters serve the delegate), §10.1 (Copilot `auto` routed,
      the served model of D10);
    - §21 row 67 `copilot-cli` (leave 66 out);
    - §23.28 "GitHub Copilot CLI (FAC, PRV, OCG)" with SCN-FAC-22 to SCN-FAC-49, SCN-PRV-129 to SCN-PRV-140 and
      SCN-OCG-15 to SCN-OCG-16 as in this change's spec.
  - Tests: `.venv/bin/python scripts/check_spec.py docs/SPEC.md` is clean;
    `tests/unit/config/test_schema.py::test_reference_config_validates_with_placeholder_commit` passes;
    `tests/unit/docs` passes.
- [ ] 6.2 Runbook, skill, CHANGELOG (design D19). Depends on 1.1 to 5.1.
  - `docs/runbook.md`: a new 10.8 "A GitHub Copilot CLI profile" (experimental; the profile; the token: a fine-grained
    PAT owned by a person, Copilot Requests, its billing and the ToS line of R1; `l4 doctor --fix` installs the pinned
    tarball and warms the cache; npm `@github/copilot@1.0.102` with Node 22 or later as a person's alternative; a judge
    on `auto` is routed, so pin a model; the rate-limit stop and the denial tripwire; what is unrecorded until the live
    recording); 7.1's list of delegate adapters; 7.4's major line for Copilot CLI 2; the contents list.
  - `plugins/l4/skills/l4/references/adopt.md`: a Copilot profile example and the token step.
  - `CHANGELOG.md`: `## 0.4.27 (unreleased)` above `## 0.4.25` with Added (the adapter, its four modes, the pin and
    install, PRQ-22), Changed (the agent-CLI cache key moves once: the catalog gains `agent:copilot-cli`; a kiro-cli
    rule now reads the routed adapters). Grep `tests/` for asserts on the newest CHANGELOG heading first and change
    any that this section breaks.
  - Tests: `tests/unit/docs` passes.

## 7. Close

- [ ] 7.1 Full suite, simulation, review. Orchestrator. Depends on 6.1 and 6.2.
  - The whole unit suite in the background (in shards if needed); `l4 simulate --all`; `npx --yes
    @fission-ai/openspec@1.14.0 validate copilot-cli --strict`; an independent review of the diff against this
    change's spec and design §8.

## 8. Live recording (release gate)

- [ ] 8.1 One GitHub-routed recording session (design D17, §2.3, §6; L4-FAC-022). Orchestrator, with the owner's
  fine-grained PAT stored as the masked secret `COPILOT_GITHUB_TOKEN` of the owner's dummy repository (never a
  consumer). Depends on 7.1. The last task.
  - In CI on a GitHub-hosted `ubuntu-24.04` runner (x64): `l4 doctor --ci --fix` installs copilot 1.0.102 (record the
    digest check and the warm cache path); `l4 doctor --live` passes LIVE-001 for a `copilot-cli` profile.
  - Record with the real adapter, small prompts, a handful of calls: a judge pinned to a model of the plan and one on
    `auto` (the `session.info` line of `l4_no_tools`, the reply, `assistant.message.model`), a delegate read, an
    implementer step with Serena on (the MCP file and `--allow-tool=<server>`), and with an OpenAI-family model if the
    plan has one (`apply_patch` approval); the usage files (`totalNanoAiu`, `aiCreditsStatus`); one run with a
    syntactically valid but wrong token built at run time (the GitHub-routed 401 or 403 shape). Record a 402 or a 429
    only if one happens; make no call to provoke one.
  - Never print the token or account data; check the redaction of every stream before it is committed.
  - Write the redacted streams to `tests/fixtures/recorded/copilot-cli/1.0.102/` with a `README.txt` (job ids, the
    date, the models), regenerate `src/l4/recorded_versions.json` (`copilot-cli: ["1.0.102"]`), and add parse tests on
    them (SCN-FAC-49).
  - Answer design §2.3 and every [I], [G] and [U] row of design §6 in `docs/live/copilot-cli/README.md`.
  - If a recorded shape differs from design D3 to D8 or D10 (another reply field, another error shape, a served id
    under a pinned model that only the server could know): stop, amend the design and the spec, then fix the mapping
    and its tests. Only then is the change releasable.
