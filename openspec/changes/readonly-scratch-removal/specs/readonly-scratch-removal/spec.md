## Purpose

Every agent step and every gate starts with an empty private scratch cache, also after a step whose Go commands left
read-only module directories in it.

## ADDED Requirements

### Requirement: Removing a scratch cache first makes its read-only directories writable
The harness SHALL remove the private trees of a step (an agent step's temp directory and scratch caches, a gate's
scratch caches, a verification round's own caches) with a removal that, when an entry cannot be removed, opened or
listed for a `PermissionError`, makes the directory holding it and the entry writable and readable, only inside the
removed tree and never through a symlink, and tries once more; it SHALL do so on every Python the harness supports
(3.11 has no `onexc`).
A removal at the start of a step that still fails SHALL raise naming the path; one at the end SHALL log a warning and
go on.

#### Scenario: the next agent step gets an empty scratch after Go filled the last one
- **WHEN** `agent-tmp/scratch-cache/GOMODCACHE` holds a directory with mode 0o555 that holds a file with mode 0o444,
  and the agent's temp directory is reset for the next step
- **THEN** the reset succeeds and `GOMODCACHE` under the new scratch is an empty directory

#### Scenario: a directory the step left unreadable is removed
- **WHEN** the agent's temp directory holds a directory with mode 0o000 that holds a subdirectory and a file (a test
  suite that checks permission errors can leave one), and the temp directory is reset for the next step
- **THEN** the reset succeeds and the directory is gone

#### Scenario: a planted link does not make the removal touch a file outside
- **WHEN** the scratch holds a symlink to a file outside it whose mode is 0o444, and the scratch is removed
- **THEN** the link is gone and the outside file keeps its content and mode 0o444

#### Scenario: a failed removal at the end of a step is a warning
- **WHEN** the removal of a step's scratch at the end of the step raises `PermissionError` after the retry
- **THEN** a warning names the path and the step's result is unchanged
