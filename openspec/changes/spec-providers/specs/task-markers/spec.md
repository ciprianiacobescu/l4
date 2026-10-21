## Purpose

Defines the single, byte-safe writer of task markers in `tasks.md` (SPEC §4.6, principle P4) and the post-step guard that reverts every other change an agent makes to that file.

## ADDED Requirements

### Requirement: L4-TMW-001 (part a) One-byte marker change
A marker change MUST modify exactly one byte, the marker character at the task's marker offset. File length, line endings (LF, CRLF, bare CR), indentation, any UTF-8 BOM and every other byte MUST be unchanged. A marker whose bracket interior is not exactly one byte (for example OpenSpec's `[]` or `[ x]`) MUST be refused.

#### Scenario: SCN-TMW-01 (+) One-byte marker write with CRLF
- **GIVEN** a CRLF `tasks.md` with `- [ ]* 2.3 Add retry`
- **WHEN** the harness marks 2.3 done
- **THEN** exactly one byte differs (`' '`→`x`), file length and line endings unchanged, write was atomic.

#### Scenario: SCN-TMW-N7 (−) Marker with a multi-byte interior is refused
- **GIVEN** a `tasks.md` containing the OpenSpec-legal line `- [ x] 1.1 Parse input` and the line `- [] 1.2 Emit output`
- **WHEN** the harness is asked to mark 1.1 or 1.2 done
- **THEN** `MarkerWriteError` is raised, the file on disk is byte-identical to before, and no temp file is left behind.

#### Scenario: SCN-TMW-N8 (−) A BOM and bare-CR lines do not shift the offset
- **GIVEN** a `tasks.md` that starts with the UTF-8 BOM `EF BB BF`, has a task on its first line and mixes LF, CRLF and bare CR terminators
- **WHEN** the harness marks the first-line task done
- **THEN** exactly one byte differs, the BOM is still present, and every terminator is unchanged.

### Requirement: L4-TMW-001 (part b) Atomic locked verified write
The marker write MUST be atomic (temp file in the same directory, fsync, rename), MUST run under a per-file lock that serialises concurrent writers in one process and across processes, and MUST be verified by re-reading the file and comparing it with the expected single-byte result.

#### Scenario: SCN-TMW-06 (+) Concurrent marker writes are serialised
- **GIVEN** two threads marking different tasks of the same file
- **WHEN** both write
- **THEN** both markers land, file length unchanged, each write verified.

#### Scenario: SCN-TMW-N9 (−) A foreign edit between read and write aborts the write
- **GIVEN** the file changed on disk (other bytes, same length) after the writer read it but before it renamed the temp file
- **WHEN** the writer completes its read-modify-verify cycle
- **THEN** `MarkerWriteError` names the path, the foreign edit is not overwritten by a stale copy, and no partial file remains.

### Requirement: L4-TMW-002 Revert every non-marker change to tasks.md
After every agent step the harness MUST compare `tasks.md` with its pre-step copy. Any difference other than harness-written marker bytes MUST be reverted and logged as `guard.violation` with `path: tasks.md`.

#### Scenario: SCN-TMW-04 (−) Agent rewords tasks.md → reverted
- **GIVEN** an agent step that changes a task title and flips a marker
- **WHEN** the post-step guard runs
- **THEN** `tasks.md` is restored byte-exact to the pre-step copy plus only harness-written markers; `guard.violation{path: tasks.md}` is logged; the attempt continues.
