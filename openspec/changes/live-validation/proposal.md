## Why

Nothing in the harness counts as done until it has run for real. The owner's rule for this build is explicit: the work
is not finished until the flows have been run on the dummy repository. This change owns the non-functional
requirements (L4-NFR-001..006) and the live scenario of SPEC section 20.4 on `example-group/dummy-agentic` (GitLab 17.5.2 CE,
project id 118) through runner #12 `l4-runner`, so every earlier change has an end-to-end oracle that is not
the harness's own output.

## What Changes

- Add live tests under `tests/live/` that drive the five items of the walking-skeleton exit criterion in order
  (doctor job on the runner, red-then-green by a real agent CLI, verification with one independent judge, MR ready and
  post-merge archive MR after a human merge, ambiguity -> `questions.md` -> committed answer resumes) and observe the
  results through the raw GitLab REST API (pipelines, jobs with `runner.id`, commits and trailers, labels, statuses,
  files), never through the harness's own forge client.
- Add the seeded dummy-repository fixture (`tests/fixtures/dummy-agentic/`), the human-run seed/reset scripts and the
  runbook of the documented install commands.
- Add the benchmarks and audits that prove the NFRs: 200-unit planning speed, per-step overhead, determinism,
  approved runtime dependencies, platform matrix, and the GA audit of `[U]` facts.
- Add the full (M2) live scenario: Codex excluded by configuration, forced clarification, forced verifier failure ->
  fix unit -> PASS -> archive, and the GitHub parity run plus the release check that blocks `v1.0.0` without both.

## Capabilities

### New Capabilities

- `non-functional`: speed, overhead, determinism, dependency, platform and evidence requirements (L4-NFR-001..006)
  and the section 20.4 live scenario on GitLab and GitHub.

### Modified Capabilities

None.

## Impact

Owned paths (tests and scripts only; no production code):

- `tests/live/`, `tests/perf/`, `tests/unit/nfr/`, `tests/unit/live/`, `tests/fixtures/dummy-agentic/`
- `scripts/live/` (seed, reset, evidence), `scripts/check_wheel_deps.py`, `scripts/check_ga.py`,
  `scripts/check_release.py`, `docs/live-validation.md`

Depends on every other change; the M1 live steps run only after `bootstrap-core`, `spec-providers`, `state-vcs-locks`,
`agent-factory`, `implementer-tdd-loop`, `clarification-loop`, `verifier` and `forge-and-ci` M1 slices exist, and on
the human prerequisites listed in the runbook (project access token, masked CI variable, agent logins on the runner).
