# Every gate runner empties the tool caches

## Why

A consumer repository's delivery plan stopped after a person merged its unit: `postcheck_failed`, `test failed (report
missing: .l4-out/junit-admin-ui.xml)`. The same code had just passed every gate of the unit's verification in the
same CI job image, and the merged revision changed nothing the admin-ui Vitest suite reads. Every other report of the
test gate was written.

L4-SEC-035 says the tool caches (`node_modules/.cache`, `.vite`, `.vite-temp`, `.vitest-cache`) are empty at the start
of every gate that does not build the environment: "the harness empties them before each gate in every mode", and
bwrap puts a tmpfs over each. Only one runner does that [V, code]. `reset_tool_caches` has one caller,
`Workbench.run_gate_spec`, which the implementer and the verifier use. The post-merge check of L4-YOLO-009
(`l4.yolo.postcheck._run`) and the gate dry run (`l4.gates.dryrun`, which `l4 yolo check` and the adoption check run)
build their own `gate_sandbox_spec` and call `run_gate` directly. `read_only_mounts` lists a tmpfs only for a tool
cache that already exists as a real directory. After the fresh `pnpm install` of the setup gate, none of the four
exists, so the test gate gets `node_modules` read-only with no writable `.vite-temp` and no `.vitest-cache`. Vite 5+
then cannot bundle the TypeScript config into `.vite-temp` (it tolerates only `EACCES` there; L4 0.4.29), Vitest stops
before it writes its JUnit report, and the report is missing [I: the gate log stays on the runner and is not uploaded;
the code path and the symptom are those of 0.4.29's `baseline_failed`].

Neither runner passes the tracked environment paths either (`tracked`), so a `node_modules` folder that git tracks
would be bound read-only and its tool caches reset there, unlike in the workbench.

## What Changes

- The post-merge check and the gate dry run empty (or make) the tool caches of the tree before every gate that does
  not build the environment, before they build that gate's sandbox spec, so `read_only_mounts` finds each cache and
  bwrap gets its tmpfs. Both pass the tracked environment paths to `gate_sandbox_spec` and to the reset.
- The tracked-paths lookup of the workbench (`Workbench._tracked_env`: `git ls-files` over `.venv`, `node_modules` and
  `**/node_modules/**`) becomes a module-level function that all three runners use.
- `docs/SPEC.md`: L4-SEC-035 names the runners that empty the caches (the workbench's gates, the post-merge check of
  L4-YOLO-009 and the gate dry run). A new scenario, SCN-SEC-106, covers the post-merge check; the change table gains
  row 75. CHANGELOG gets a 0.4.32 entry under Fixed.

## Impact

- Code: `l4.sandbox.envdirs` (the tracked-paths function), `l4.implementer.workbench` (uses it), `l4.yolo.postcheck`
  and `l4.gates.dryrun` (reset and `tracked` per gate).
- Not changed: `gate_sandbox_spec` stays a pure builder, and the doctor's sandbox probe (`checks_sandbox`) keeps its own
  scratch tree with no `node_modules`.
- Security: the reset is the protection L4-SEC-035 already promises (a planted `.vite/deps` or `.vitest-cache` entry
  cannot reach a later gate). The two runners now give it.
- Consumers: a delivery plan stopped with `postcheck_failed` on this cause resumes with `l4 yolo resume <plan> --reason
  …` once its target pins 0.4.32; the check runs again.
- Out of scope: surfacing the failing post-merge gate's log in the CI job log (the stop names a log file that exists
  only on the runner); a separate change.
