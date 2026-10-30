# `l4 doctor` on a person's computer says when `l4 run` will refuse there

## Why

Since 0.4.43 a local `l4 run` or `l4 verify` without a usable sandbox refuses up front (L4-SEC-041). `l4 doctor` still
says nothing about it on such a computer: the bubblewrap row (PRV-002) is skipped off Linux and SANDBOX-002/003 skip
when `bwrap` is absent [V]. A person learns it only when the run refuses. docs/SPEC.md also promises a SANDBOX-001
warning for macOS (SCN-NFR-05, `sandbox.mode: user`), but SANDBOX-001 is not registered and `mode: user` is not built
(it exits 2), and the artefacts line of a local run says "(CI: job artifacts)".

## What changes

- A doctor row LOCAL-001 (warn, scope `local` only, so `l4 doctor --ci` never runs it and a CI job is never failed by
  it): `l4 run`/`l4 verify` will refuse on this computer, with the reason `sandbox_refusal` gives (on macOS the ways
  out); a mode that is not built yet (`user`, `container`) is a fail of the row naming the mode, not a crash. Pass: the
  sandbox the run would use.
- SANDBOX-001 stays unregistered: its row in docs/SPEC.md is the full credential and isolation probe of L4-SEC-005,
  which is a separate change (implementation-map 1.13). A row with that id doing less would mislead. SCN-NFR-05 is
  amended to what is true: LOCAL-001 warns on macOS; `mode: user` is not built.
- The artefacts line says "(CI: job artifacts)" only in a CI job (`in_ci_job`).

## Impact

- Code: a doctor check module (`src/l4/doctor/checks_sandbox.py` or a new `checks_local.py` listed in
  `CHECK_MODULES`), `src/l4/progress.py` (`log_artefacts`) and its caller in `src/l4/orchestrator.py`.
- Spec: the doctor table of L4-DOC-001 gets LOCAL-001; SANDBOX-001's row says it is not registered yet; SCN-NFR-05
  amended; SCN-DOC-10 to SCN-DOC-13 added; change-table row 101. Runbook §11 (`resume` takes no spec edit,
  L4-OPS-001) fixed by the docs pass.
- Not in this change: fetch before reading for `status`, `plan`, `resume` and `run --unit` off CI (it reverses
  L4-OPS-014's last sentence, SCN-CLI-12 and L4-CLI-003's rule for `plan`/`resume`): 0.4.45.
