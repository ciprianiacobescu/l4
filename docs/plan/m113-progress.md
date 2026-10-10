# M1.13 progress (2026-10-07)

Branch `m113` from `main` 5aa112b, plan commit cc2a7a9. Labels: [V] verified, [I] inferred, [U] not checked. Nothing was pushed.

## Covered by M1.12 / open (see the plan for citations)

| Item | Status |
|---|---|
| W-C1 test-only finding | open, built (lines 8-13) |
| W-C2 escalated resume | open, built (lines 14-20) |
| W-C3 unfreeze words | partly covered (M1.12 F2), the note built (lines 21-23) |
| W-C4 weak audit tests | partly covered (M1.11 W7, M1.12 K2), built (lines 24-26) |
| W-C5 in-process tests | covered (M1.12 K3) |
| W-C6 designed stop | covered (M1.12 K4); `idle.py` 502 built (line 27) |
| W-C7 clarifier cannot unfreeze | covered by design (M1.10 C2 + M1.12 F2) |
| MAG result path | built (lines 1-7) |

## Commits (author CiprianSpot, no trailers)

`99b264e` MAG, `c6c7e6d` and a follow-up W-C2, `c2e2cb1` W-C1, `9e03c6b` W-C3, `4efc5fd` W-C4, `0f81491` W-C6, and a last
commit for two tests that the full run showed to follow the new texts.

## Full suite, in chunks (background mode, `-p no:cacheprovider`)

| Chunk | Collected | passed | skipped | xfailed | failed |
|---|---|---|---|---|---|
| agents, availability, llm | 558 | 553 | 5 | 0 | 0 |
| verifier, implementer, gates | 1346 | 1341 (+1 after rerun) | 3 | 1 | 1 (stale `.pyc`, see 1) |
| orchestrator, archive, state, vcs, specs | 602 | 599 (+1 after fix) | 2 | 0 | 1 (see 2) |
| the other unit dirs and `test_*.py` | 1952 | 1946 (+1 after fix) | 5 | 0 | 1 (see 3) |
| contract, scenarios, integration, live | 122 | 59 | 63 | 0 | 0 |
| **total** | **4580** | **4501** | **78** | **1** | 0 |

4501 + 78 + 1 = 4580 = collected. The three failing tests were fixed or re-run alone and pass; the chunks were not run
again whole. `uv run ruff check .` passes; `python3 scripts/check_spec.py docs/SPEC.md` reports no problem.

1. `test_testwriter.py::test_audit_rules_and_header_block`: the file was edited to the same byte size within a second of its
   earlier version, so a stale assertion-rewrite `.pyc` was used [V: passes after deleting it]. Not a code defect.
2. `archive/test_hooks.py::test_an_escalated_unit_note_...`: it pinned the old text "a resume does not apply"; now updated.
3. `security/test_protected.py::test_contract_list_...`: the protected list has 23 globs now (`.l4-result/**`); updated.

## Deviations and limits (read these)

1. **MAG: a symlink, not a bind mount.** The plan's own choice (bwrap would change the argv mirrored in
   `sandbox-probe.sh`, and does not exist for `sandbox.mode: none`). The alias is made before and removed after every
   implementer step. Whether magnitude-qwen then writes it right is [U]; it needs a live run, which was not made.
2. **W-C2: the label gives one round**, and only when the fix rounds are used up; `--extend-iterations` and `--extend-cost`
   stay refused. A unit escalated for another reason resumes with no extension. The loop was shown end to end on the fake
   adapter (`test_ladder_fix_resume.py`, about 150 s); the label path is tested at the sweep level with the resume stubbed, not
   against a real escalated unit.
3. **W-C1: the classification is conservative** (title speaks of tests, criterion `pass`, no scenario, judge or human
   finding). A judge finding worded differently stays a red/green task and would halt as before [I]. The early check (`discriminate_extra`)
   runs only for a task that cites a criterion; a coverage chore is unchanged. Each such step costs up to two more gate runs.
4. **W-C4: `hasattr` is rejected only as a cascade** (two or more constant names on one object); a single `hasattr` stays
   allowed, as M1.11 W7 decided. Name checks cover imported names and module attributes of shown source files, not
   methods of an instance. The rule against snapshotting excluded logs is a prompt rule plus showing `design.md`; it is not
   checked by code.
5. **W-C6:** `l4_idle.py` is a new repository helper; the scratch `idle.py` in the session scratchpad now calls it and retries
   an exit 2 four times. The 502 count of the real proxy is [U]; 3 retries with a backoff is a guess (`L4GL_RETRIES`).
6. The SIGINT interrupt test did not fail in any chunk, so no lone re-run was needed.
