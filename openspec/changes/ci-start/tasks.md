## 1. The forge call and the command (L4-OPS-024)

- [x] 1.1 Write the tests first (tests/unit/forge/test_start_run.py, test_dispatch_continuation.py,
  test_gitlab_continuation.py; the fakes `FakeGitHub` in _github_helpers.py with `queued_runs` and the run listing, and
  `RefAwareGitLab`; the CLI spec test that every command has a §2.1 row). Then implement design D1 and D2, including a
  GitLab running pipeline blocking the start. Cases: SCN-OPS-46 to SCN-OPS-50.
  Result: tests first (the new tests failed on the missing `l4.ci.start` module and the missing SPEC row), then
  `Forge.base_activity` on the GitHub, GitLab and local forges (GitHub and GitLab share one listing read with
  `base_runs`; a finished run with an unreadable end time makes the forge say "cannot tell"), `l4.ci.start` with
  `l4 ci start [--if-idle DURATION]` wired in `_SPECS`, `HANDLERS` and `OWNING_CHANGE`, and the one SPEC 2.1 row the
  CLI spec test needs. 19 command tests (GitHub and GitLab through their fakes, the local forge, every exit code) and
  9 forge tests. Deviations: the started line carries no run link, because `Forge.start_run` answers a bare word and
  GitHub's dispatch returns no run; the command uses `how_to_start` and the forge's own `start_run`, not
  `start_run_result`, since it must tell a missing token from a forge that cannot tell (both exit 3, with different
  lines); a forge that cannot tell prints its line on stderr, as every exit 3 does.

- [x] 1.2 Review fixes: runs of the harness on other branches count (the job's concurrency group is the repository's);
  a 200 that is not JSON is "cannot tell"; a GitHub run held for approval is active; GitLab ends come from
  `updated_at`. Tests first.
  Result: GitHub `base_activity` now lists `l4.yml` without a branch filter (100 runs); active = queued, in progress,
  waiting, requested, pending and completed with `action_required` (which has no end time); the end = the newest other
  completed run of any branch. GitLab reads the project's pipelines and keeps those on the base, the project's default
  branch and `forge.branch_prefix` (the command passes the configured prefix; `base_activity` takes it as a keyword,
  default `l4/`), counting canceling and scheduled as active, with the end from `updated_at` (`finished_at` as the
  fallback). Both catch `(ForgeError, ValueError)` and answer None, so a non-JSON 200 is exit 3. `base_runs`,
  `dispatch_continuation`, `start_run` and the relay are untouched. Design D1, the L4-OPS-024 text, SCN-OPS-51 and the
  proposal (including the laptop-clock-skew risk line) are amended. Deviation: the GitLab default branch comes from one
  extra project read per call; when the project names none, only the base and unit refs count.

## 2. Checks

- [x] 2.1 Run only the test files you changed or added, once each, then ruff check and ruff format on the changed
  files. Report the counts.
  Result: the six test files that were changed or added (tests/unit/ci/test_ci_start.py, tests/unit/forge/test_start_run.py,
  test_dispatch_continuation.py, test_gitlab_continuation.py, tests/unit/cli/test_dispatch.py and
  tests/unit/test_spec_commands.py) pass together: 121 passed. `tests/unit/forge/test_relay_run.py` (14 passed) was
  run once as well, because `_active_runs` in the GitHub forge now reads its listing through a shared helper. `ruff
  check` and `ruff format --check` are clean on all 13 changed Python files.
