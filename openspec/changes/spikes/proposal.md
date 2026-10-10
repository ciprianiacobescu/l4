## Why

The SPEC (docs/SPEC.md) rests on facts about external tools that are labelled [U] (unverified) or only [D]/[I]: the headless
contract of four agent CLIs, the JSON shapes of the OpenSpec CLI, the zero-cost quota probes, Playwright and the agents
inside bubblewrap, atomic pushes and custom refs on both forges, Kiro headless workspace trust, and the TDD-evidence
rules (stub allow-lists, zero-value stubs, suppression scans) per language. If a [U] fact is wrong the adapter, the
verifier or the sandbox built on it is wrong. SPEC section 21 row 0 therefore requires one short report per spike
before the implementer loop (change 6) and the verifier (change 8) are planned, and SPEC section 24.1 item 7 forbids closing a change
that depends on an unverified [U] fact. A live attempt to inventory the reference runner has also already failed once (job died in
"prepare environment"), which shows how much of the environment is still a black box.

## What Changes

- Add a `docs/spikes/` directory with one report per spike: `<nn>-<name>.md` containing question, method, exact
  commands, observed output, verdict (promising / adapt / reject) and the SPEC amendment if any.
- Add recorded raw CLI outputs under `tests/fixtures/cli/<tool>/<version>/` (the contract-test fixtures of SPEC
  section 20.2, reused by change 5 `agent-factory`) and three fixture repositories under `tests/fixtures/tdd/{python,typescript,go}/`
  with the must-catch and must-pass gaming cases of SPEC section 21 row 0.
- Milestone M1 (runnable now on macOS with Claude Code 2.1.288, OpenCode 1.18.33, a local Codex 0.160.0 binary, OpenSpec 1.14.0,
  Python 3.14 via uv, Docker): runner inventory (retry gated on a maintainer fix), OpenSpec JSON outputs, headless contract of
  claude / opencode / codex / kiro-cli, quota probes, Python TDD fixture.
- Milestone M2: bubblewrap on the runner, Playwright in bubblewrap (SCN-SPK-01), container-backed serve without the Docker socket
  (SCN-SPK-02), agents inside bubblewrap, Kiro trust, atomic pushes and custom refs on GitHub and GitLab 17.5, GitLab CI/CD
  components, `CLAUDE_CODE_OAUTH_TOKEN`, HOME/cache mounts, read-only `.git`, bubblewrap on GitHub-hosted runners, TypeScript and Go
  fixtures, and a user-local provisioning spike that feeds change 12.
- Where a spike fails or shows the SPEC is wrong, amend SPEC.md in the same change as the spike report (SPEC section 24.1 item 4).

## Capabilities

### New Capabilities

None. This change produces evidence, fixtures and SPEC amendments only (`skip_specs: true` in `.openspec.yaml`); the scenarios
SCN-SPK-01 and SCN-SPK-02 stay in SPEC.md Part II and are referenced by the M2 spike tasks that settle them.

### Modified Capabilities

None.

## Impact

- Owned paths: `docs/spikes/**`, `tests/fixtures/cli/**`, `tests/fixtures/tdd/**`, `scripts/spikes/**` (throwaway probe scripts), and
  amendments to `docs/SPEC.md` where a verdict is "adapt" or "reject".
- No file under `src/l4/` is created or changed. No change depends on this one at build time except by reading its reports:
  changes 5 (agent-factory), 6 (implementer-tdd-loop), 8 (verifier), 11 (sandbox-security) and 12 (runner-provisioning) are
  planned only after the relevant report exists.
- Needs: macOS dev machine (M1), the reference runner `l4-runner` through CI jobs only (it is a black box without SSH), and a GitHub
  test repository for the push spikes (SPEC open question Q5).
