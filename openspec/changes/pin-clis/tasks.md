Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key, event, constant and signature is in
  `design.md` (D1 to D12 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree, with its own `.venv`. Never change git configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `pin-clis <n>.<m>: …`, with no
  trailer and no local path.
- No test touches the network: a `Fetcher` is a fake that serves bytes built in the test (a small zip made with
  `zipfile`, members a few bytes long), and the digest table is monkeypatched for it. `kiro_platform`'s libc is a
  parameter or a stub, never the host's. Only tasks 1.1, 3.1 and 6.1 download, and they write nothing into the
  worktree but their evidence file.
- Never install anything outside a scratch directory, never run an agent CLI with a credential, and never read
  `~/.kiro`, `~/.claude`, `~/.codex`, `~/.config/opencode` or any credential file.
- Never wait on a process with `while pgrep …` (it matches itself). Run commands in the foreground with a timeout.
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- Merge order (design "Collisions"): this change ships first and depends on nothing in `opencode-v2` (paused). Do not
  add `opencode2` anywhere: `opencode-v2` rebases onto this change later and extends `MAJOR_WORDS`, `ci.cli_versions`
  and the exact pin to it.

Test worlds: `tests/unit/provision/conftest.py` (`FIXTURES`, the install runners), `tests/unit/provision/test_install.py`
(`InstallRunner`), `tests/unit/provision/test_plan.py`, `tests/unit/runner/test_prereqs_steps.py` (`TEXT`, `pin`,
`steps`, `_bash_function`, the `as_runner` stub pattern of `_check_opencode`), `tests/unit/availability/test_probes.py`,
`tests/unit/doctor/` (the `DoctorContext` builders), `tests/unit/agents/test_kiro_judge.py`.

## 1. The catalog: the Kiro pin, the archive, the major gate (design D1, D3, D8, D11; L4-PRV-042, L4-OCG-005)

- [ ] 1.1 Evidence, no code. In a scratch directory outside the worktree, download the four 2.32.0 Linux zips of
  design D1 once, compute their sha256 and compare them with the table; open each with `zipfile` and confirm the three
  `kirocli/bin/` members are regular files (the design read the central directories, not the bytes). Write the result
  (URLs, sizes, digests, member list, date) to `docs/live/pin-clis/README.md`. Stop and report to the orchestrator if
  one digest or member differs. Delete the downloads.

- [ ] 1.2 The constants and the archive. Tests first, `tests/unit/provision/test_catalog.py`:
  `test_kiro_is_pinned_and_in_catalog_pins` (SCN-PRV-118: `ADAPTER_PINS["kiro-cli"] == "2.32.0"`,
  `catalog_pins()["agent:kiro-cli"] == "2.32.0"`, no `INSTALLER_URLS["kiro-cli"]`);
  `test_catalog_hash_moves_with_the_kiro_pin` (SCN-PRV-118, monkeypatch `KIRO_VERSION` and `ADAPTER_PINS`);
  `test_the_kiro_digest_table` (every version has the four Linux keys and 64 hex digits each; the 2.32.0 row equals
  design D1 as literals; the pin is in the table);
  `test_kiro_archive_url` (`linux-x64` and `linux-arm64-musl` give the D1 URLs; no `latest` anywhere in the module);
  `test_kiro_platform_follows_the_glibc` (SCN-PRV-115: libc `glibc 2.35` on arm64 gives `linux-arm64-musl`, on x64
  `linux-x64`; `glibc 2.39` on arm64 gives `linux-arm64`; `None` gives the musl key);
  `test_kiro_platform_refuses_other_systems` (`darwin-arm64` raises `ValueError`);
  `test_manual_command_for_kiro` (Linux, through `kiro_platform` with a stubbed libc: the versioned URL of that
  platform key, its digest, `sha256sum -c`, `unzip`, the three `install -m 755`; darwin: the `.dmg` URL and
  `KIRO_DMG_SHA256`). Update `tests/unit/provision/test_plan.py:55`
  (`test_profile_in_any_role_chain_counts_and_kiro_is_unpinned`, which expects the installer line): rename it and
  expect the Linux manual line. Code: `src/l4/provision/catalog.py` (Contracts); delete the module comment "Kiro's installer takes
  no version argument … it is installed as released" and the `catalog_pins()` docstring's "Kiro and bwrap have no pin"
  (bwrap keeps its sentence), and the `SUPPORTED_MAJORS` comment's "Only `opencode`". Run: those two files.

- [ ] 1.3 The major gate's wording. Tests first, `tests/unit/provision/test_catalog.py`:
  `test_supported_majors_follow_the_pins` (`{"opencode": 1, "kiro-cli": 2}`);
  `test_kiro_major_problem_names_the_cause_and_the_pin` (SCN-OCG-11: `kiro-cli 3.0.0` gives design D8's sentence with
  `2.32.0`; with pin `2.28.0` it names `2.28.0`; `kiro-cli 2.33.0` gives None);
  `test_the_opencode_texts_are_unchanged` (the exact L4-OCG-002 sentence, and the `MAJOR_WORDS` reason, `_verified`
  and fail-closed texts for `opencode` equal today's literals in `runner.py`, `install.py` and `checks_env.py`).
  Code: `MAJOR_WORDS` (the `MajorWords` named tuple of the Contracts), `major_problem`. The callers move to the table
  in 2.3, 2.4 and 5.2. The existing `tests/unit/test_versions.py`, `tests/unit/test_versions_major.py` and every
  `major_problem` caller's tests must pass unchanged. Run: those files and `tests/unit/availability tests/unit/doctor`.

- [ ] 1.4 The maintenance script. Tests first, new `tests/unit/test_kiro_pin_script.py` (load the script with
  `importlib.util.spec_from_file_location`, as `tests/unit/test_release_script.py` does; there is no
  `tests/unit/scripts/`) with a small `index.json` fixture written in the test (two versions, one without its musl
  zips): `test_prints_the_row_and_the_prereqs_lines`, `test_a_missing_zip_exits_1`, `test_an_unknown_version_exits_1`.
  The script reads `https://prod.download.cli.kiro.dev/stable/index.json` or, in tests, a file (`--index PATH`).
  Code: `scripts/dev/kiro_pin.py` (D11). Run: that file.

## 2. Provisioning: the Kiro install, exact pins in CI, the override (design D2, D4, D5, D9; L4-PRV-042, L4-PRV-043, L4-PRV-045, L4-OCG-005)

- [ ] 2.1 The configuration key. Tests first, new `tests/unit/config/test_cli_versions.py`:
  `test_the_default_is_empty`; `test_an_unknown_adapter_is_a_load_error`, `test_a_malformed_version_is_a_load_error`
  (SCN-PRV-127, the D9 texts); `test_an_override_never_crosses_the_major` (SCN-PRV-126: `kiro-cli 3.0.0` and
  `opencode 2.0.32`, the D9 text); `test_effective_pins_name_their_source`. Red from the spec commit on, because
  SPEC §3.2 already holds `cli_versions: {}`: `tests/unit/config/test_schema.py::test_version_only_file_yields_full_defaults`
  and `::test_reference_config_validates_with_placeholder_commit` (`extra_forbidden` on the key). This task makes them
  pass without editing them. Also `test_the_schema_imports_alone` (a fresh interpreter, `subprocess` with
  `sys.executable -c "import l4.config.schema"`, exits 0): `catalog.py` imports `L4Config` from `schema.py`, so the
  validator imports the catalog inside its function body (design D9). Code: `src/l4/config/schema.py`
  (`CiCfg.cli_versions` and its validator), `catalog.effective_pins`. Run: that file and `tests/unit/config`. Do this
  task first in section 2.

- [ ] 2.2 The cache key. Tests first, `tests/unit/provision/test_catalog.py` and the `l4 ci cache-key` tests under
  `tests/unit/ci/`: `test_an_override_of_a_cli_in_use_changes_the_key` (SCN-PRV-125);
  `test_an_override_of_an_unused_cli_keeps_the_key`; `test_no_override_keeps_the_catalog_key`. Code: `catalog_hash`,
  `clis_cache_hash`. Run: those files.

- [ ] 2.3 Exact in CI, the floor rule elsewhere (design D5, as decided: a person's `--fix` keeps today's behaviour).
  Tests first, `tests/unit/provision/test_plan.py`: `test_ci_plans_a_cli_of_another_version` (SCN-PRV-119: `codex
  0.161.0`, `replace_present=True`, reason `found 0.161.0, pinned 0.160.0`); `test_local_keeps_a_cli_of_another_version`
  (SCN-PRV-120: `already present`, no download); `test_local_below_the_floor_installs_the_pin` (SCN-PRV-120: `codex
  0.150.0`, `min_version` `0.160.0`, no `--ci`: `planned` with `found 0.150.0, need 0.160.0`, today's behaviour; every
  existing test that expects a local install over a CLI below its floor passes unchanged);
  `test_local_kiro_below_the_floor_is_planned` (Linux, `kiro-cli 2.27.1`, `min_version` `2.32.0`, no `--ci`:
  `planned`); `test_local_kiro_of_another_major_is_manual` and `test_ci_kiro_of_another_major_is_planned` (SCN-OCG-13,
  the D8 reason); `test_a_kiro_override_without_digests_is_manual` (SCN-PRV-127: no fetch, the D9 text);
  `test_kiro_on_macos_is_manual` (SCN-PRV-117: missing, and present below its floor; no fetch, the D4 line);
  `test_an_override_is_the_target` (SCN-PRV-125: reason ends `(ci.cli_versions)`);
  `test_an_override_below_the_floor_is_skipped` (D9: `{kiro-cli: "2.28.0"}`, `min_version` `2.32.0`, today's
  `_floor_above_pin` text); `test_self_provision_false_still_skips_in_ci` (`allow_install=False`,
  `replace_present=True`, a drifted codex: `skipped`); the existing `_floor_above_pin` and OpenCode (L4-OCG-004) tests
  pass unchanged. Code: `src/l4/provision/runner.py` (`is_satisfied`, `plan_fixes`, the reasons from `MAJOR_WORDS`),
  `catalog.required_tools`. Run: `tests/unit/provision`.

- [ ] 2.4 The Kiro install. Tests first, new `tests/unit/provision/test_install_kiro.py` (a fake `Fetcher` that
  records URLs and serves a zip built in the test, a monkeypatched `KIRO_SHA256`, a `kiro_platform` stub, an install
  runner whose `kiro-cli --version` answers from the installed file): `test_installs_the_three_members_with_mode_755`
  (SCN-PRV-113: only the versioned URL fetched, the three files and no other new file, no member run, the temporary
  directory gone, `applied` with `kiro-cli 2.32.0`); `test_a_digest_mismatch_changes_nothing` (SCN-PRV-114: `failed`,
  both digests, existing files byte-identical, exit 3 through `install_planned`); `test_a_linked_member_fails` and
  `test_a_missing_member_fails` (SCN-PRV-116); `test_an_oversized_member_fails`;
  `test_a_wrong_major_after_the_install_names_the_path` (L4-OCG-005: the D8 `_verified` text);
  `test_ci_replaces_a_regular_kiro_file` (SCN-OCG-13); `test_a_staging_error_removes_the_staged_files` (SCN-PRV-116:
  the fake fails while writing the second member; no `.*.tmp.*` left in `~/.local/bin`, the old files byte-identical);
  `test_a_403_is_failed_with_the_manual_command` (the fake raises `OfflineError(host, "HTTP 403")`: `failed`, the
  message names `HTTP 403` and the manual command); `test_ci_verifies_the_exact_version` (SCN-PRV-119: a fake Claude
  installer that leaves `claude 2.1.300` under `replace_present=True`: `failed` with `installed 2.1.300, but 2.1.288
  (pinned) is needed`, exit 3 through `install_planned`; without `replace_present`, a missing Claude installed at
  2.1.288 is `applied` as today). Update `tests/unit/provision/test_install.py:163`
  (`test_kiro_runs_its_saved_installer_without_a_version`, which runs the Kiro installer) into an archive test.
  Code: `src/l4/provision/install.py` (`_Ctx.replace_present`, `_install_kiro`, `_install_agent`, `_verified` with
  the exact check and the `MAJOR_WORDS` texts, `zipfile.BadZipFile` in `_apply`). Run: `tests/unit/provision`.

- [ ] 2.5 The doctor's switch. Tests first, `tests/unit/doctor/test_fix_provision.py` (new or existing):
  `test_ci_passes_replace_present` (`l4 doctor --ci --fix` reaches `install_planned` with `replace_present=True`, and
  `l4 doctor --fix` with False); `test_the_survey_matches`. Code: `src/l4/doctor/context.py` (`ci`),
  `src/l4/doctor/run.py`, `src/l4/doctor/checks_provision.py`. Run: `tests/unit/doctor`.

## 3. Self-update off (design D7; L4-PRV-044)

- [ ] 3.1 Evidence first, no code. With the pinned Codex 0.160.0 in a scratch npm prefix, an empty `HOME` and
  `CODEX_HOME`, and no credential variable, run `codex exec --skip-git-repo-check --ephemeral -s read-only -c
  check_for_update_on_startup=false -` with `x` on stdin and a 60 s timeout. Then, in the same isolated `HOME`, start
  `codex app-server` with stdin closed and a 20 s timeout, and record whether its standard error mentions an update.
  Record stdout, stderr and the exit codes in `docs/live/pin-clis/README.md`. Pass: no configuration error that names
  the key (a login error is expected). If 0.160.0 refuses the key, stop and report to the orchestrator; do not drop the
  switch. If `app-server` shows an update check, report it to the orchestrator (design D13, decision 3) instead of
  adding the switch yourself.

- [ ] 3.2 Claude Code. Tests first: `tests/unit/agents/test_claude_code.py`
  `test_extra_env_turns_updates_off`; `tests/unit/availability/test_probes.py` `test_claude_probe_env_turns_updates_off`
  (SCN-PRV-122: `binary`, `auth` and `hello`); `tests/unit/provision/test_paths.py` or `test_install.py`
  `test_an_installer_env_keeps_the_updater_off_and_claude_install_on` (SCN-PRV-122: `scrub_env` holds
  `DISABLE_AUTOUPDATER=1` and no `DISABLE_UPDATES`, also with `DISABLE_UPDATES=1` in the host environment);
  `tests/unit/doctor/test_checks_env.py` `test_claude_version_reads_turn_the_updater_off` (the `env` passed to
  `ctx.run` for `claude --version` holds `DISABLE_AUTOUPDATER=1`). Code: `src/l4/agents/claude_code.py`,
  `src/l4/availability/probes.py` (`probe_claude`, `_binary` for `claude`), `src/l4/provision/runner.py`
  (`scrub_env`), `src/l4/doctor/checks_env.py` and `checks_agents.py` (the `claude --version` reads). Run: those files
  and `tests/contract/agents`.

- [ ] 3.3 Codex. Tests first, `tests/unit/agents/test_codex.py` `test_every_exec_argv_turns_the_update_check_off`
  (SCN-PRV-123: implementer and judge; the switch follows `-c project_doc_max_bytes=0`), and in
  `tests/unit/availability/test_probes.py` the hello argv. Update every test or recorded argv that compares the whole
  argv. Code: `src/l4/agents/codex.py`, `src/l4/availability/probes.py`. Run: those files and `tests/contract/agents`.

- [ ] 3.4 Kiro. Tests first, `tests/unit/agents/test_kiro_cli.py` (or `test_kiro_judge.py`):
  `test_the_implementer_home_holds_only_the_update_setting` (SCN-PRV-123: `settings/cli.json` is exactly
  `{"app.disableAutoupdates": true}` beside the agent file); `test_the_judge_home_is_unchanged`. Code:
  `src/l4/agents/kiro_cli.py` (`write_harness_agent`). Run: `tests/unit/agents`.

- [ ] 3.5 The runner image, PRQ-21. Tests first, `tests/unit/runner/test_prereqs_steps.py`:
  `test_prq21_merges_the_claude_setting` (SCN-PRV-124: run the script's merge function, extracted with
  `_bash_function`, with an `as_runner` stub on a temporary `settings.json`; skip when `jq` is missing);
  `test_prq21_merges_the_kiro_setting` (a missing `~/.kiro/settings/cli.json` becomes `{"app.disableAutoupdates":
  true}`, an existing one keeps its other keys); `test_prq21_never_writes_disable_updates`;
  `test_prq21_runs_no_agent_cli` (the PRQ-21 functions hold no `kiro-cli` or `claude` command);
  `test_prq21_leaves_a_file_that_is_not_json`; `test_prq21_sets_the_kiro_setting_only_with_kiro`; `test_script_parses`
  passes. Code: `scripts/runner/prereqs.sh` (PRQ-21 after PRQ-12). Run: that file.

## 4. prereqs.sh PRQ-12 (design D6; L4-PRV-043, L4-OCG-005)

- [ ] 4.1 Tests first, `tests/unit/runner/test_prereqs_steps.py`. Replace
  `test_kiro_is_pinned_to_the_version_of_the_maintainer_machine_as_a_floor` and
  `test_kiro_apply_updates_an_installed_cli_without_a_prompt_and_installs_only_a_missing_one` (they assert the floor,
  `kiro-cli update` and the installer) with: `test_kiro_is_pinned_exactly` (`pin("KIRO_VERSION") == "2.32.0"`, the
  check compares with `=`); `test_kiro_apply_downloads_the_versioned_archive_and_checks_it` (SCN-PRV-121: no `kiro-cli
  update`, no `cli.kiro.dev/install`, `stable/$KIRO_VERSION/`, `sha256sum -c`, three `install -m 755`, no `/dev/tty`);
  `test_check_kiro_is_exact_and_names_a_wrong_major` (SCN-PRV-121, SCN-OCG-14, through the `as_runner` stub:
  `kiro-cli 2.32.0` passes, `kiro-cli 2.33.0` fails with `pinned 2.32.0`, `kiro-cli 3.0.0` fails with `Kiro CLI 3; L4
  runs Kiro CLI 2`). `tests/unit/provision/test_catalog.py`: `test_kiro_pin_and_digests_equal_prereqs_sh` (the four
  `KIRO_SHA256_*` defaults equal the catalog's pin row). Code: `scripts/runner/prereqs.sh` (top block, PRQ-12; the
  comment above `apply_kiro` that explains `kiro-cli update` goes, and no comment keeps the words `kiro-cli update`,
  which task 7.2 greps for), and `scripts/runner/inspect.sh`'s egress list probes `https://prod.download.cli.kiro.dev`
  instead of `https://cli.kiro.dev` (the host the archive comes from). Run: those files.

## 5. The probe and doctor (design D8, D10; L4-PRV-046, L4-OCG-005, L4-PRV-045)

- [ ] 5.1 The probe. Tests first, `tests/unit/availability/test_probes.py`:
  `test_binary_detail_has_the_pin_and_its_source` (SCN-PRV-128); `test_a_kiro_cli_3_fails_binary_before_any_model_call`
  (SCN-OCG-11: no `auth`, `quota` or `hello` call recorded); `test_an_override_is_the_pin_the_probe_reports`;
  `tests/unit/availability/test_fallback.py`: `test_the_probe_identity_moves_with_the_override` (the new `pin`
  parameter of `probe_identity`, Contracts; both callers pass `self._ctx.pins.get(profile.adapter)`),
  `test_the_binary_text_names_a_drift_only`, `test_selected_has_binary_pinned_only_on_a_drift` (SCN-PRV-128). Code:
  `src/l4/agents/base.py` (`ProbeCtx.pins`), `src/l4/agents/factory.py`, `src/l4/availability/probes.py`
  (`_binary`), `src/l4/availability/fallback.py` (`probe_identity`, `_step_text`, `to_event`). Run:
  `tests/unit/availability tests/unit/agents`.

- [ ] 5.2 ENV-004 and LIVE-005 for Kiro. Tests first, `tests/unit/doctor/test_checks_env.py` and the LIVE-005 tests:
  `test_env_004_fails_a_kiro_cli_3_without_min_version`, `test_env_004_fails_closed_on_a_kiro_cli_without_a_version`
  (SCN-OCG-12: `kiro-cli reports no version, so its Kiro CLI major cannot be checked`; the OpenCode text unchanged)
  and `test_live_005_makes_a_kiro_cli_3_an_error` (SCN-OCG-12). Code: `src/l4/doctor/checks_env.py` (`_cli_problem`:
  the fail-closed text from `MAJOR_WORDS`), `src/l4/doctor/checks_agents.py` (the effective pin, the wording from the
  table). Run: `tests/unit/doctor`.

- [ ] 5.3 ENV-015. Tests first, new `tests/unit/doctor/test_env_015.py`: `test_passes_at_the_pins_and_names_overrides`
  (SCN-PRV-125); `test_warns_on_a_drift_with_both_versions_and_the_fix` (SCN-PRV-120);
  `test_leaves_a_missing_cli_and_a_wrong_major_to_env_004`; `test_skips_without_an_agent_cli`;
  `test_the_install_fix_is_attached` (and `--ci --fix` then passes in a fake install world);
  `test_a_manual_override_warns_and_exits_0` (SCN-PRV-127, the second world: `kiro-cli 2.32.0` present,
  `{kiro-cli: "2.31.1"}`: the action `manual`, ENV-015 a warning, exit 0). Code: `src/l4/doctor/checks_env.py`
  (`ENV_015`), `src/l4/doctor/checks_provision.py` (`attach_fix("ENV-015", INSTALL_FIX)`). Run: `tests/unit/doctor`.

## 6. Live (design D2, D5)

- [ ] 6.1 On the owner's dummy repository (public, throwaway), GitHub-hosted `ubuntu-24.04`, action delivery at this
  branch's commit, a `kiro-cli` profile in a role chain, and a cold agent-CLI cache: the `doctor` step installs
  `kiro-cli 2.32.0` from the versioned archive (the log names the URL, no `latest`), ENV-015 passes, the cache is saved
  under a key with the Kiro pin, and a second run restores it and installs nothing. Then set `ci.cli_versions`
  `{kiro-cli: "2.28.0"}` and run once more: the key changes and 2.28.0 is installed. Record the run ids and the lines in
  `docs/live/pin-clis/README.md`. The owner deletes the dummy repository.

## 7. Docs and CHANGELOG (design D12)

- [ ] 7.1 Tests first, new `tests/unit/docs/test_pin_clis_docs.py`: `test_the_spec_has_the_requirements_and_scenarios`
  (`**L4-PRV-042 ` to `**L4-PRV-046 ` in order before the doctor table; `**L4-OCG-005 ` after `**L4-OCG-004 `;
  `#### SCN-PRV-113 ` to `#### SCN-PRV-128 ` and `#### SCN-OCG-11 ` to `#### SCN-OCG-14 ` in increasing order; §3.2
  holds `cli_versions: {}`; the doctor table has `| ENV-015 |`; `| 57 | \`pin-clis\` |`);
  `test_the_runbook_has_the_kiro_gate_and_the_versions_section` (7.4 holds `is Kiro CLI 3; L4 runs Kiro CLI 2`; 10.7
  names `ci.cli_versions`, `ENV-015`, `l4 doctor --ci --fix`, that a person's `l4 doctor --fix` replaces only a CLI
  below its `min_version`, and `harness.delivery: action` for an override's cache);
  `test_the_runner_readme_has_prq12_and_prq21` (PRQ-12 names the versioned archive and `sha256sum`, not
  `cli.kiro.dev/install`; a PRQ-21 row; PRQ-20 named as reserved);
  `test_the_skill_names_the_pins` (`adopt.md` names `ci.cli_versions` and "move the pin before", and section 4d no
  longer says "2.32.0 or newer"; `operate.md`'s error table has the Kiro major sentence, ENV-015's line and
  `ci.cli_versions:`);
  `test_the_changelog_names_the_pins` (in `## 0.4.20 (unreleased)`: `2.32.0`, `ci.cli_versions`,
  `DISABLE_AUTOUPDATER`, `Kiro CLI 3`, `ENV-015`, `kiro-cli update`). Change
  `tests/unit/docs/test_yolo_guardrails_docs.py:25` from `assert "## 0.4.20 (unreleased)" not in changelog` to
  `assert changelog.index("## 0.4.20 (unreleased)") < changelog.index("## 0.4.19 (")`. The other docs tests must pass
  (`test_run_continuation_docs.py` and `test_yolo_go_docs.py` read the 0.4.19 head, which stays). Code: `CHANGELOG.md`
  (the lines below, above `## 0.4.19`), `docs/runbook.md` (7.4, new 10.7, the contents list), `docs/runner/README.md`
  (PRQ-12 row, PRQ-21 row, PRQ-20 reserved, the "Kiro installer" sentence), `plugins/l4/skills/l4/references/adopt.md`
  (the pins, holding one, section 4d),
  `plugins/l4/skills/l4/references/operate.md`. The SPEC text is already in this branch; change it only to match the
  code, with the orchestrator. Run: `tests/unit/docs tests/unit/skills`, `scripts/check_spec.py docs/SPEC.md`,
  `openspec validate pin-clis --strict`.

- [ ] 7.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`,
  `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every changed file, and
  `.venv/bin/mypy` on the changed src files. Done when all pass, `git status` is clean, `git grep -n
  "cli.kiro.dev/install" -- src scripts` and `git grep -n "kiro-cli update" -- src scripts` find nothing.

## CHANGELOG lines (`## 0.4.20 (unreleased)`; task 7.1 writes them as they stand)

### Added
- Kiro CLI is pinned: `kiro-cli 2.32.0`. On Linux the harness installs it from the versioned archive
  (`https://prod.download.cli.kiro.dev/stable/2.32.0/…`, gnu or musl as Kiro's installer chooses), checks its sha256
  against a table in the harness, and puts `kiro-cli`, `kiro-cli-chat` and `kiro-cli-term` into `~/.local/bin`. It
  never installs `latest` and runs no installer script. On macOS it installs nothing: `l4 doctor` names the pinned
  disk image and its sha256 (L4-PRV-042).
- `ci.cli_versions` holds an agent CLI at another version of the same major, for example `{kiro-cli: "2.28.0"}`.
  Provisioning, the probe and doctor use it, and it changes the agent-CLI cache key. A Kiro version is installed only
  when the harness holds its digests (2.27.1, 2.28.0, 2.32.0). Move your harness pin to 0.4.20 before you add the key
  (L4-PRV-045).
- Doctor `ENV-015` (warn) reports each agent CLI's version against its pin, and names an override. The probe's
  `binary` step records `pin` and `pin_source`; its line reads `binary 2.33.0 (pinned 2.32.0)` on a drift, and
  `availability.selected` records `binary_pinned` then (L4-PRV-046).
- `prereqs.sh` PRQ-21 turns the background update off for the runner user's Claude Code (`DISABLE_AUTOUPDATER` in
  `~/.claude/settings.json`) and Kiro (`app.disableAutoupdates` in `~/.kiro/settings/cli.json`), merging one key into
  each file with `jq` and running no agent CLI (L4-PRV-044).

### Changed
- In CI (`l4 doctor --ci --fix`) an agent CLI of another version than its pin is replaced by the pin, and the install
  must then report exactly the pin; before, a CLI at least the profile's `min_version` was kept. `l4 doctor --fix` on
  your own machine works as before: a CLI that meets `min_version` is kept (`ENV-015` now names both versions and the
  command), and one below it is installed at the pin. A Kiro CLI 3 on your machine is left alone, with the fix named
  (L4-PRV-043).
- A `kiro-cli` of another major than 2 is refused at the probe's `binary` step, by `ENV-004` and `LIVE-005` (an
  error), by `l4 doctor --fix` and by `prereqs.sh` PRQ-12: `kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install
  kiro-cli 2.32.0 …` (L4-OCG-005).
- No agent CLI that L4 starts updates itself: Claude Code runs and probes get `DISABLE_AUTOUPDATER=1` and
  `DISABLE_UPDATES=1` (installers `DISABLE_AUTOUPDATER=1` only), every `codex exec` gets `-c
  check_for_update_on_startup=false`, and the implementer's private `KIRO_HOME` holds `app.disableAutoupdates`
  (L4-PRV-044).
- `prereqs.sh` PRQ-12 installs the pinned Kiro archive with the same digest check and no longer runs `kiro-cli
  update`. `KIRO_VERSION` is exact, not a floor (L4-PRV-043).
- Every agent-CLI cache key changes once with this release (the catalog now pins Kiro), and every cached probe
  result is probed again once (its identity now holds the pin).
